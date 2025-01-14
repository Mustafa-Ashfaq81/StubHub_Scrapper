import time
import csv
import logging
import json

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    ElementClickInterceptedException,
    ElementNotInteractableException
)

####################################################################
# Logging Configuration
####################################################################
logging.basicConfig(
    filename='stubhub_scraper.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

####################################################################
# Configuration Section
####################################################################

LOCATION_TO_SEARCH = "capital one arena"

DEFAULT_TIMEOUT = 20
OUTPUT_CSV_FILE = "stubhub_output.csv"

# Decide how many events to scrape before stopping (for testing/progress)
MAX_EVENTS_TO_SCRAPE = 8

####################################################################
# Utility Functions
####################################################################

def wait_for_element(driver, by_method, selector, timeout=DEFAULT_TIMEOUT):
    """
    Wait for an element to be present on the page and return it.
    Raises TimeoutException if not found within the specified timeout.
    """
    return WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((by_method, selector))
    )

def wait_for_clickable(driver, by_method, selector, timeout=DEFAULT_TIMEOUT):
    """
    Wait for an element to be clickable on the page and return it.
    Raises TimeoutException if not found within the specified timeout.
    """
    return WebDriverWait(driver, timeout).until(
        EC.element_to_be_clickable((by_method, selector))
    )

def click_element(driver, by_method, selector, timeout=DEFAULT_TIMEOUT):
    """
    Wait for an element to be clickable, then click it.
    """
    el = wait_for_clickable(driver, by_method, selector, timeout)
    el.click()

def send_keys_element(driver, by_method, selector, text, timeout=DEFAULT_TIMEOUT):
    """
    Wait for an element to be present and clickable, then clear and send_keys.
    """
    el = wait_for_clickable(driver, by_method, selector, timeout)
    el.clear()
    el.send_keys(text)

####################################################################
# Main Scraping Logic
####################################################################

def main():
    logging.info("=== Starting StubHub Scraper ===")

    options = webdriver.ChromeOptions()
    # Uncomment if you prefer headless mode:
    # options.add_argument("--headless")

    service = ChromeService()
    driver = webdriver.Chrome(service=service, options=options)

    try:
        logging.info("Navigating to StubHub login page...")
        driver.get("https://my.stubhub.com/secure/login")
        driver.maximize_window()
        
        wait_for_manual_login(driver)
        go_to_sell(driver)
        search_location(driver, LOCATION_TO_SEARCH)
        navigate_to_parking_tab(driver)

        # SCRAPE EVENTS TWICE:
        # 1) Immediately after landing on the page
        events_first_pass = scrape_events(driver)
        # 2) After waiting a few seconds for the page to possibly reload/refresh
        time.sleep(5)  # Adjust as needed
        events_second_pass = scrape_events(driver)
        
        # Combine them
        combined_events = events_first_pass + events_second_pass

        # Deduplicate events based on unique fields (e.g., name, date, location)
        unique_events = list({f"{e['name']}_{e['date']}_{e['location']}": e for e in combined_events}.values())

        logging.info(f"Scraped first pass: {len(events_first_pass)} events, "
                     f"second pass: {len(events_second_pass)} events, "
                     f"combined: {len(unique_events)} events total.")

        # Remove events that appear to be placeholders (N/A)
        filtered_events = [
            e for e in unique_events
            if not (e["date"] == "N/A" and e["time"] == "N/A" and e["name"] == "N/A" and e["location"] == "N/A")
        ]
        if not filtered_events:
            logging.warning("No valid events to process after filtering. Exiting.")
            return
        logging.info(f"Filtered out N/A events. Remaining unique events: {len(filtered_events)}")

        final_data = []
        original_window = driver.current_window_handle  # keep track of the main tab

        for idx, event_info in enumerate(filtered_events):
            if idx >= MAX_EVENTS_TO_SCRAPE:
                logging.info(f"Reached the maximum of {MAX_EVENTS_TO_SCRAPE} events. Stopping early.")
                break

            logging.info(f"=== Processing event {idx+1}/{len(filtered_events)} ===")
            
            success = interact_with_event_and_select_tickets(
                driver, event_index=idx, original_window=original_window
            )
            
            if not success:
                logging.warning(f"Event at index {idx} could not be opened or processed. Skipping seat scraping.")
                continue

            # Now we are in the new tab if success is True. Attempt seat scraping:
            all_seat_labels = get_all_seats_labels(driver)
            logging.info(f"Found {len(all_seat_labels)} seats for event {idx+1}.")

            for seat_idx, seat_label in enumerate(all_seat_labels):
                logging.info(f"Selecting seat {seat_idx+1}/{len(all_seat_labels)}: '{seat_label}'")
                seat_success = select_seat_in_dropdown(driver, seat_idx)
                if not seat_success:
                    logging.warning(f"Could not select seat index {seat_idx}. Skipping.")
                    continue

                # Now scrape ticket price & listings
                per_ticket_price, listings = interact_with_ticket_price_page(driver)
                if not listings or per_ticket_price is None:
                    logging.warning(f"No listings found or ticket price missing for seat '{seat_label}'")
                    continue

                for listing in listings:
                    row = {
                        "event_date": event_info.get("date", ""),
                        "event_time": event_info.get("time", ""),
                        "event_name": event_info.get("name", ""),
                        "event_location": event_info.get("location", ""),
                        "selected_seat": seat_label,
                        "per_ticket_price": per_ticket_price,
                        "listing_title": listing.get("title", ""),
                        "listing_price": listing.get("price", ""),
                        "listing_passes": listing.get("passes", ""),
                        "listing_rating_score": listing.get("rating_score", ""),
                        "listing_rating_label": listing.get("rating_label", ""),
                    }
                    final_data.append(row)

            # Finished seat scraping for this event. Close this new tab & return to the main listing
            if len(driver.window_handles) > 1 and driver.current_window_handle != original_window:
                driver.close()
            driver.switch_to.window(original_window)
            time.sleep(1)  # small pause

            # Write partial data so we can see progress
            write_data_to_csv(final_data, OUTPUT_CSV_FILE)
            logging.info(f"Finished scraping event {idx+1}. Data so far saved to {OUTPUT_CSV_FILE}.\n")

    except Exception as e:
        logging.error(f"Main script error: {str(e)}", exc_info=True)

    finally:
        logging.info("Closing browser.")
        driver.quit()
        logging.info("=== StubHub Scraper Finished ===")

####################################################################
# Step-by-step Functions
####################################################################

def wait_for_manual_login(driver, timeout=300):
    """
    Wait for the user to manually log in and detect the logged-in state.
    """
    logging.info("Waiting for user to complete manual login...")
    print("Please complete the login process manually (including CAPTCHA).")
    print(f"You have {timeout // 60} minutes to complete the login.")

    try:
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.XPATH, "//a[contains(text(), 'Sell')]"))
        )
        logging.info("Login detected. Resuming script execution.")
        print("Login successful. Resuming automated tasks.")
    except TimeoutException:
        logging.error("Timeout waiting for manual login. Exiting script.")
        print("Login timeout exceeded. Please try again.")
        driver.quit()
        exit(1)

def close_popups(driver):
    logging.info("Attempting to close any pop-ups.")
    try:
        cookie_close_xpath = "//button[@aria-label='Close']"
        popups = driver.find_elements(By.XPATH, cookie_close_xpath)
        for popup in popups:
            popup.click()
            logging.info("Closed a pop-up.")
    except Exception:
        logging.debug("No pop-ups to close or could not close pop-ups.")

    # Check for captcha
    try:
        driver.find_element(By.XPATH, "//iframe[contains(@src, 'captcha')]")
        logging.error("Captcha detected. Cannot proceed.")
    except NoSuchElementException:
        logging.info("No captcha detected.")

def go_to_sell(driver):
    """
    Navigates to the 'Sell Tickets' section.
    """
    logging.info("Navigating to 'Sell Tickets' page.")
    try:
        driver.get("https://www.stubhub.com/sell")
        time.sleep(3)
        logging.info("Arrived at Sell page.")
    except Exception as e:
        logging.error(f"Error navigating to Sell tickets: {e}", exc_info=True)

def search_location(driver, location_query):
    """
    Enters the location query into the search bar for the 'Sell Tickets' flow.
    """
    logging.info(f"Searching for location: {location_query}")
    try:
        close_popups(driver)

        search_input = WebDriverWait(driver, DEFAULT_TIMEOUT * 2).until(
            EC.element_to_be_clickable((By.XPATH, "//input[@placeholder='Search your event and start selling']"))
        )
        logging.info("Search input found. Interacting with it.")

        search_input.clear()
        search_input.send_keys(location_query)
        search_input.send_keys(Keys.ENTER)
        time.sleep(4)
        logging.info(f"Location '{location_query}' searched successfully.")

    except TimeoutException as e:
        logging.error(f"Error searching location: {e}. Saving debug information.")
        with open("debug_page_source.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        driver.save_screenshot("debug_screenshot.png")

    except Exception as e:
        logging.error(f"Unexpected error searching location: {e}", exc_info=True)

def navigate_to_parking_tab(driver):
    """
    Clicks the 'Parking' tab after the search results are displayed.
    """
    logging.info("Navigating to 'Parking' tab.")
    try:
        parking_tab = WebDriverWait(driver, DEFAULT_TIMEOUT).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Parking')]"))
        )
        logging.info("'Parking' tab found. Clicking it.")
        parking_tab.click()
        time.sleep(3)
        logging.info("Successfully navigated to 'Parking' tab.")
    except TimeoutException as e:
        logging.error(f"Error navigating to 'Parking' tab: {e}.")
        driver.save_screenshot("navigate_to_parking_tab_error.png")
    except Exception as e:
        logging.error(f"Unexpected error while navigating to 'Parking' tab: {e}", exc_info=True)

def scrape_events(driver):
    """
    Scrape event details from the event listing page using resilient selectors.
    """
    logging.info("Starting to scrape event details.")
    try:
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CLASS_NAME, "sc-1pn28cb-0"))
        )
        event_cards = driver.find_elements(By.CLASS_NAME, "sc-1or4et4-0")
        if not event_cards:
            logging.warning("No events found on the page.")
            return []

        scraped_events = []
        for index, card in enumerate(event_cards):
            try:
                date = time_text = name = location = "N/A"

                try:
                    date = card.find_element(By.CLASS_NAME, "sc-yi86cf-2").text
                except NoSuchElementException:
                    logging.debug(f"Date not found for event card {index}")

                try:
                    time_text = card.find_element(By.CLASS_NAME, "sc-ntazun-5").text
                except NoSuchElementException:
                    logging.debug(f"Time not found for event card {index}")

                try:
                    name = card.find_element(By.CLASS_NAME, "sc-18gjf30-0").text
                except NoSuchElementException:
                    logging.debug(f"Name not found for event card {index}")

                try:
                    location = card.find_element(By.CLASS_NAME, "sc-ntazun-30").text
                except NoSuchElementException:
                    logging.debug(f"Location not found for event card {index}")

                event_details = {
                    "date": date,
                    "time": time_text,
                    "name": name,
                    "location": location,
                }
                scraped_events.append(event_details)
                logging.info(f"Scraped event: {event_details}")

            except Exception as e:
                logging.warning(f"Error extracting data for event card {index}: {e}")

        logging.info(f"Total events scraped: {len(scraped_events)}")
        return scraped_events

    except Exception as e:
        logging.error(f"Error while scraping events: {e}", exc_info=True)
        return []

def interact_with_event_and_select_tickets(driver, event_index, original_window):
    """
    1. Re-locate the event cards on the original tab.
    2. Click on the event at `event_index`.
    3. Wait for the new tab, switch to it.
    4. Select ticket quantity = 1, click next, next, ...
    5. Select E-Tickets, attempt "I'll upload later".
    
    Returns True if we successfully reached the seat dropdown page. 
    Returns False if anything times out or fails.
    """
    try:
        logging.info(f"Attempting to interact with event at index {event_index}.")
        # Switch to the original window
        driver.switch_to.window(original_window)

        # Re-find the event cards
        event_cards = WebDriverWait(driver, 10).until(
            EC.presence_of_all_elements_located((By.CLASS_NAME, "sc-1or4et4-0"))
        )
        if event_index >= len(event_cards):
            logging.error(f"Event at index {event_index} does not exist on the page.")
            return False

        # Wait until clickable, then click
        WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable(event_cards[event_index])
        )
        event_cards[event_index].click()
        logging.info(f"Clicked on the event at index {event_index}.")

        # Wait for the second tab
        WebDriverWait(driver, 30).until(EC.number_of_windows_to_be(2))

        # Identify the newly opened tab
        new_windows = [w for w in driver.window_handles if w != original_window]
        if not new_windows:
            logging.error("No new window was opened after clicking the event.")
            return False

        new_window = new_windows[0]
        driver.switch_to.window(new_window)
        logging.info("Switched to the new window/tab.")

        # Now proceed with ticket quantity question
        WebDriverWait(driver, 30).until(
            EC.visibility_of_element_located((By.XPATH, "//div[contains(text(), 'How many tickets do you have?')]"))
        )
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")

        quantity_dropdown = WebDriverWait(driver, 30).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, 'select[name="quantity"]'))
        )
        Select(quantity_dropdown).select_by_visible_text("1 Ticket")
        logging.info("Selected 1 ticket from the dropdown.")

        # Click first continue
        first_continue_button = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.CLASS_NAME, "sc-6f7nfk-0"))
        )
        first_continue_button.click()
        logging.info("Clicked the first Continue button.")

        # Second continue
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located(
                (By.XPATH, "//form[@novalidate]//button[normalize-space()='Continue' and not(@disabled)]")
            )
        )
        second_continue_button = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable(
                (By.XPATH, "//form[@novalidate]//button[normalize-space()='Continue' and not(@disabled)]")
            )
        )
        second_continue_button.click()
        logging.info("Clicked the second Continue button.")

        # Ticket type question
        WebDriverWait(driver, 30).until(
            EC.visibility_of_element_located(
                (By.XPATH, "//div[contains(text(), 'What type of tickets are you listing?')]")
            )
        )
        e_tickets_radio = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable(
                (By.XPATH, "//label[.//span[contains(text(),'E-Tickets')]]//input[@type='Radio']")
            )
        )
        e_tickets_radio.click()
        logging.info("Selected E-Tickets.")

        # Attempt to find & click "I'll upload later"
        ill_upload_later_radio = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable(
                (By.XPATH, "//label[.//span[contains(text(), \"I'll upload later\")]]")
            )
        )
        driver.execute_script("arguments[0].scrollIntoView(true);", ill_upload_later_radio)
        ill_upload_later_radio.click()
        logging.info("Selected 'I'll upload later' option.")

        # Final continue
        final_continue_button = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable(
                (By.XPATH, "//button[normalize-space()='Continue' and not(@disabled)]")
            )
        )
        final_continue_button.click()
        logging.info("Clicked the final Continue button.")
        return True

    except TimeoutException as e:
        logging.error(f"Timeout error: {e}", exc_info=True)
        # Gracefully close this new tab if it opened
        for w in driver.window_handles:
            if w != original_window:
                driver.switch_to.window(w)
                driver.close()
        # Switch back
        driver.switch_to.window(original_window)
        return False
    except Exception as e:
        logging.error(f"Error interacting with the event at index {event_index}: {e}", exc_info=True)
        # Gracefully close any new tab
        for w in driver.window_handles:
            if w != original_window:
                driver.switch_to.window(w)
                driver.close()
        driver.switch_to.window(original_window)
        return False

def get_all_seats_labels(driver):
    """
    Retrieves seat labels from the "Where are your seats?" dropdown on the new tab/page.
    Returns a list of seat labels. If we cannot find the dropdown, returns [].
    """
    try:
        logging.info("Retrieving all seat labels from the dropdown page.")
        dropdown = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".css-13jwkg0-control"))
        )
        dropdown_arrow = dropdown.find_element(By.CSS_SELECTOR, ".css-1og4hos-indicatorContainer")
        dropdown_arrow.click()
        logging.info("Clicked on the dropdown arrow to reveal seat options.")

        options = WebDriverWait(driver, 15).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div[class*='menu'] div"))
        )
        labels = [option.text for option in options if option.text.strip()]

        logging.info(f"Extracted seat labels: {labels}")

        # Close the dropdown
        driver.execute_script("arguments[0].click();", dropdown_arrow)

        return labels

    except TimeoutException:
        logging.error("Timeout while retrieving seat labels.")
        return []
    except Exception as e:
        logging.error(f"An error occurred while retrieving seat labels: {e}", exc_info=True)
        return []

def select_seat_in_dropdown(driver, seat_index):
    """
    Opens the seat dropdown again, selects seat at `seat_index`, clicks "Continue".
    Returns True if successful, False otherwise.
    """
    try:
        logging.info(f"Selecting seat at index {seat_index}.")
        dropdown = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".css-13jwkg0-control"))
        )
        dropdown_arrow = dropdown.find_element(By.CSS_SELECTOR, ".css-1og4hos-indicatorContainer")
        dropdown_arrow.click()

        options = WebDriverWait(driver, 15).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div[class*='menu'] div"))
        )
        if seat_index >= len(options):
            logging.warning(f"Seat index {seat_index} is out of range (only {len(options)} available).")
            # Click outside or close
            driver.execute_script("arguments[0].click();", dropdown_arrow)
            return False

        desired_option = options[seat_index]
        driver.execute_script("arguments[0].scrollIntoView(true);", desired_option)
        desired_option.click()
        logging.info(f"Clicked on seat index {seat_index} in the dropdown.")

        # Click the "Continue" button
        continue_button = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.XPATH, "//button[normalize-space()='Continue']"))
        )
        continue_button.click()
        logging.info("Clicked the 'Continue' button after seat selection.")
        return True

    except TimeoutException as e:
        logging.error(f"Timeout while selecting seat {seat_index}: {e}", exc_info=True)
        return False
    except Exception as e:
        logging.error(f"An error occurred while selecting seat index {seat_index}: {e}", exc_info=True)
        return False

def interact_with_ticket_price_page(driver):
    """
    Extract ticket price and scrape all listings on the Compare page. 
    If no new window is opened, it might open in the same tab. 
    We handle both cases. 
    Returns (price, listings).
    """
    try:
        logging.info("Interacting with the ticket price page...")

        ticket_price_input = WebDriverWait(driver, 30).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, "input[name='ticketPrice_non_decimal']"))
        )
        ticket_price = ticket_price_input.get_attribute("value")
        logging.info(f"Extracted per ticket price: US$ {ticket_price}")

        compare_link = WebDriverWait(driver, 30).until(
            EC.element_to_be_clickable((By.LINK_TEXT, "Compare similar tickets"))
        )
        logging.info("Clicking on 'Compare similar tickets'.")

        old_handles = driver.window_handles
        current_url = driver.current_url

        compare_link.click()

        # Wait until new tab or page load
        WebDriverWait(driver, 30).until(
            lambda d: (
                len(d.window_handles) > len(old_handles)
                or d.current_url != current_url
                or "listings-container" in d.page_source
            )
        )

        # If a new tab is opened, switch to it
        new_compare_tab = None
        if len(driver.window_handles) > len(old_handles):
            new_tabs = set(driver.window_handles) - set(old_handles)
            if new_tabs:
                new_compare_tab = new_tabs.pop()
                driver.switch_to.window(new_compare_tab)
                logging.info("Switched to new Compare tab.")

        listings_container = WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.ID, "listings-container"))
        )
        logging.info("Listings container loaded successfully.")

        listings = []
        last_height = driver.execute_script("return document.body.scrollHeight")

        while True:
            visible_listings = listings_container.find_elements(By.CSS_SELECTOR, ".sc-194s59m-1.ivCIjj")
            for listing in visible_listings[len(listings):]:
                try:
                    title = listing.find_element(By.CSS_SELECTOR, ".sc-1t1b4cp-0.sc-1t1b4cp-6").text
                    price = listing.find_element(By.CSS_SELECTOR, ".sc-1t1b4cp-0.sc-1t1b4cp-1").text
                    passes = listing.find_element(By.CSS_SELECTOR, ".sc-1t1b4cp-11.sc-1t1b4cp-13").text

                    rating_elements = listing.find_elements(By.CSS_SELECTOR, ".sc-5cv63s-3")
                    rating_score = rating_elements[0].text if rating_elements else ""

                    rating_label_elements = listing.find_elements(By.CSS_SELECTOR, ".sc-5cv63s-2")
                    rating_label = rating_label_elements[0].text if rating_label_elements else ""

                    listings.append({
                        "title": title,
                        "price": price,
                        "passes": passes,
                        "rating_score": rating_score,
                        "rating_label": rating_label,
                    })
                    logging.info(f"Scraped listing: {title}, {price}, {passes}, {rating_score}, {rating_label}")
                except Exception as e:
                    logging.warning(f"Error scraping a listing: {e}", exc_info=True)

            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height

        logging.info(f"Total listings scraped: {len(listings)}")

        # If we opened a new tab for compare, close it & switch back
        if new_compare_tab and new_compare_tab in driver.window_handles:
            driver.close()
            # Switch back to whichever tab was active before compare
            for wh in old_handles:
                if wh in driver.window_handles:
                    driver.switch_to.window(wh)
                    break

        return ticket_price, listings

    except TimeoutException as e:
        logging.error(f"Timeout occurred: {e}", exc_info=True)
        return None, []
    except Exception as e:
        logging.error(f"An error occurred on the ticket price page: {e}", exc_info=True)
        return None, []

def write_data_to_csv(final_data, csv_file):
    """
    Writes the combined final data to CSV with a fixed column order.
    """
    logging.info(f"Writing data to CSV: {csv_file}")
    if not final_data:
        logging.warning("No data to write to CSV.")
        print("No data to write to CSV.")
        return

    fieldnames = [
        "event_date",
        "event_time",
        "event_name",
        "event_location",
        "selected_seat",
        "per_ticket_price",
        "listing_title",
        "listing_price",
        "listing_passes",
        "listing_rating_score",
        "listing_rating_label"
    ]

    try:
        with open(csv_file, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in final_data:
                writer.writerow(row)
        logging.info(f"Wrote {len(final_data)} rows to CSV: {csv_file}")
        print(f"\nScraping complete (or partial). Data saved to '{csv_file}'.")
    except Exception as e:
        logging.error(f"Error writing data to CSV: {e}", exc_info=True)

####################################################################
# Run the Scraper
####################################################################

if __name__ == "__main__":
    main()
