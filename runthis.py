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
    # Uncomment for headless mode if desired:
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

        events = scrape_events(driver)
        logging.info(f"Scraped {len(events)} events: {events}")

        # Interact with the 7th event (index 6)
        interact_with_event(driver, event_index=8)

        # Store details of the selected event
        selected_event = events[8] if len(events) > 8 else {}

        seats = interact_with_seat_dropdown(driver)
        selected_seat = seats[0] if seats else ""

        per_ticket_price, listings = interact_with_ticket_price_page(driver)

        # Combine data into a final list of rows for CSV
        final_data = []
        for listing in listings:
            row = {
                "event_date": selected_event.get("date", ""),
                "event_time": selected_event.get("time", ""),
                "event_name": selected_event.get("name", ""),
                "event_location": selected_event.get("location", ""),
                "selected_seat": selected_seat,
                "per_ticket_price": per_ticket_price,
                "listing_title": listing.get("title", ""),
                "listing_price": listing.get("price", ""),
                "listing_passes": listing.get("passes", ""),
                "listing_rating_score": listing.get("rating_score", ""),
                "listing_rating_label": listing.get("rating_label", ""),
            }
            final_data.append(row)

        # Write the combined data to CSV
        write_data_to_csv(final_data, OUTPUT_CSV_FILE)

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
        # Wait until a specific element that indicates login success is present
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.XPATH, "//a[contains(text(), 'Sell')]"))  # Example: "Sell" button appears
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
        captcha_frame = driver.find_element(By.XPATH, "//iframe[contains(@src, 'captcha')]")
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
        # Ensure pop-ups are closed
        close_popups(driver)

        # Wait for the search input
        search_input = WebDriverWait(driver, DEFAULT_TIMEOUT * 2).until(
            EC.element_to_be_clickable((By.XPATH, "//input[@placeholder='Search your event and start selling']"))
        )
        logging.info("Search input found. Interacting with it.")

        # Clear and send the search query
        search_input.clear()
        search_input.send_keys(location_query)
        search_input.send_keys(Keys.ENTER)
        time.sleep(4)
        logging.info(f"Location '{location_query}' searched successfully.")

    except TimeoutException as e:
        logging.error(f"Error searching location: {e}. Saving debug information.")
        # Save page source and screenshot for debugging
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
        # Wait for the 'Parking' tab to be clickable
        parking_tab = WebDriverWait(driver, DEFAULT_TIMEOUT).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Parking')]"))
        )
        logging.info("'Parking' tab found. Clicking it.")
        parking_tab.click()
        time.sleep(3)  # Allow time for the page to load
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
        # Wait until the container that holds events is present
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CLASS_NAME, "sc-1pn28cb-0"))
        )
        # Locate all event cards
        event_cards = driver.find_elements(By.CLASS_NAME, "sc-1or4et4-0")
        if not event_cards:
            logging.warning("No events found on the page.")
            return []

        scraped_events = []
        for index, card in enumerate(event_cards):
            try:
                # Initialize defaults
                date = time_text = name = location = "N/A"

                # Try extracting using known classes; if not found, retain default
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
                logging.warning(f"Error extracting data for event card at index {index}: {e}")

        logging.info(f"Total events scraped: {len(scraped_events)}")
        return scraped_events

    except Exception as e:
        logging.error(f"Error while scraping events: {e}", exc_info=True)
        return []
    
def interact_with_event(driver, event_index=8):
    """
    Navigate to the specified event, select a ticket quantity, click Continue,
    and then proceed through subsequent pages by selecting required options
    and clicking Continue. Aborts gracefully if "I'll upload later" option is not found.
    """
    try:
        logging.info(f"Attempting to interact with event at index {event_index + 1}.")

        # Store the original window handle
        original_window = driver.current_window_handle

        # Locate the list of event cards
        event_cards = WebDriverWait(driver, 10).until(
            EC.presence_of_all_elements_located((By.CLASS_NAME, "sc-1or4et4-0"))
        )

        # Ensure the event exists
        if not event_cards or event_index >= len(event_cards):
            logging.error(f"Event at index {event_index + 1} does not exist.")
            return

        # Click the specified event
        event_card = event_cards[event_index]
        event_card.click()
        logging.info(f"Clicked on the event at index {event_index + 1}.")

        # Wait for a new window/tab to open and switch to it
        WebDriverWait(driver, 30).until(EC.number_of_windows_to_be(2))
        new_window = [window for window in driver.window_handles if window != original_window][0]
        driver.switch_to.window(new_window)
        logging.info("Switched to the new window/tab.")

        # Wait for the event detail page content to be visible
        WebDriverWait(driver, 30).until(
            EC.visibility_of_element_located((By.XPATH, "//div[contains(text(), 'How many tickets do you have?')]"))
        )

        # Scroll to the bottom of the page to ensure elements are in view
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")

        # Wait for and select quantity
        quantity_dropdown = WebDriverWait(driver, 30).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, 'select[name="quantity"]'))
        )
        select = Select(quantity_dropdown)
        select.select_by_visible_text("1 Ticket")
        logging.info("Selected 1 ticket from the dropdown.")

        # Click the first Continue button
        first_continue_button = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.CLASS_NAME, "sc-6f7nfk-0"))
        )
        first_continue_button.click()
        logging.info("Clicked the first Continue button.")

        # Wait for the next page to load by waiting for a new "Continue" button in the form
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located(
                (By.XPATH, "//form[@novalidate]//button[normalize-space()='Continue' and not(@disabled)]")
            )
        )

        # Locate and click the second Continue button
        second_continue_button = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable(
                (By.XPATH, "//form[@novalidate]//button[normalize-space()='Continue' and not(@disabled)]")
            )
        )
        second_continue_button.click()
        logging.info("Clicked the second Continue button.")

        # Wait for the new page to load by checking for the ticket type question
        WebDriverWait(driver, 30).until(
            EC.visibility_of_element_located((By.XPATH, "//div[contains(text(), 'What type of tickets are you listing?')]"))
        )

        # Select "E-Tickets" option
        e_tickets_radio = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable(
                (By.XPATH, "//label[.//span[contains(text(),'E-Tickets')]]//input[@type='Radio']")
            )
        )
        e_tickets_radio.click()
        logging.info("Selected E-Tickets.")

        # Wait for the "I'll upload later" option to become clickable
        ill_upload_later_radio = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable(
                (By.XPATH, "//label[.//span[contains(text(), \"I'll upload later\")]]")
            )
        )
        # Scroll to the element to ensure it's in view
        driver.execute_script("arguments[0].scrollIntoView(true);", ill_upload_later_radio)

        # Click the "I'll upload later" radio button
        ill_upload_later_radio.click()
        logging.info("Selected 'I'll upload later' option.")

        # Click the final Continue button
        final_continue_button = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable(
                (By.XPATH, "//button[normalize-space()='Continue' and not(@disabled)]")
            )
        )
        final_continue_button.click()
        logging.info("Clicked the final Continue button.")

    except TimeoutException as e:
        logging.error(f"Timeout error: {e}", exc_info=True)
    except Exception as e:
        logging.error(f"Error interacting with the event at index {event_index + 1}: {e}", exc_info=True)

def interact_with_seat_dropdown(driver):
    """
    Extract all labels from the "Where are your seats?" dropdown, select the first option,
    and click the "Continue" button.
    """
    try:
        logging.info("Interacting with the 'Where are your seats?' dropdown.")

        # Wait for the dropdown to be visible
        dropdown = WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".css-13jwkg0-control"))
        )
        logging.info("Dropdown located.")

        # Click the dropdown arrow to reveal options
        dropdown_arrow = dropdown.find_element(By.CSS_SELECTOR, ".css-1og4hos-indicatorContainer")
        dropdown_arrow.click()
        logging.info("Clicked on the dropdown arrow to reveal options.")

        # Wait for the dropdown options to load
        options = WebDriverWait(driver, 20).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div[class*='menu'] div"))
        )

        # Extract all labels from the dropdown
        labels = [option.text for option in options if option.text.strip()]
        logging.info(f"Extracted dropdown labels: {labels}")  # Log the extracted options
        if not labels:
            raise ValueError("Dropdown options are empty or not interactable.")
        
        # Select the first option in the dropdown
        first_option = options[0]
        driver.execute_script("arguments[0].scrollIntoView(true);", first_option)
        first_option.click()
        logging.info(f"Selected the first option: {labels[0]}")

        # Click the "Continue" button
        continue_button = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.XPATH, "//button[normalize-space()='Continue']"))
        )
        continue_button.click()
        logging.info("Clicked the 'Continue' button.")

        return labels

    except TimeoutException as e:
        logging.error(f"Timeout while interacting with the dropdown: {e}", exc_info=True)
        raise
    except Exception as e:
        logging.error(f"An error occurred while interacting with the dropdown: {e}", exc_info=True)
        raise

def interact_with_ticket_price_page(driver):
    """
    Extract ticket price and scrape all listings, handling cases where the 
    link opens in a new window/tab or changes the current page.
    """
    try:
        logging.info("Interacting with the ticket price page.")

        # Wait for the price input field and extract price
        ticket_price_input = WebDriverWait(driver, 60).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, "input[name='ticketPrice_non_decimal']"))
        )
        ticket_price = ticket_price_input.get_attribute("value")
        logging.info(f"Extracted per ticket price: US$ {ticket_price}")

        # Locate the "Compare similar tickets" link/button
        compare_link = WebDriverWait(driver, 60).until(
            EC.element_to_be_clickable((By.LINK_TEXT, "Compare similar tickets"))
        )
        logging.info("Clicking on 'Compare similar tickets'.")

        # Capture current window handles and URL before clicking
        old_handles = driver.window_handles
        current_url = driver.current_url

        # Click the link
        compare_link.click()

        # Wait until a new window opens, URL changes, or listings container appears
        WebDriverWait(driver, 60).until(
            lambda d: len(d.window_handles) > len(old_handles) or
                      d.current_url != current_url or
                      "listings-container" in d.page_source
        )

        # If a new window opened, switch to it
        if len(driver.window_handles) > len(old_handles):
            new_handles = set(driver.window_handles) - set(old_handles)
            if new_handles:
                driver.switch_to.window(new_handles.pop())
                logging.info("Switched to new window/tab opened by the link.")

        # Now wait for the listings container to be present
        listings_container = WebDriverWait(driver, 60).until(
            EC.presence_of_element_located((By.ID, "listings-container"))
        )
        logging.info("Listings container loaded successfully.")

        # Scroll and load all listings dynamically
        listings = []
        last_height = driver.execute_script("return document.body.scrollHeight")
        while True:
            visible_listings = listings_container.find_elements(By.CSS_SELECTOR, ".sc-194s59m-1.ivCIjj")
            for listing in visible_listings[len(listings):]:  # Avoid re-scraping already scraped listings
                try:
                    title = listing.find_element(By.CSS_SELECTOR, ".sc-1t1b4cp-0.sc-1t1b4cp-6").text
                    price = listing.find_element(By.CSS_SELECTOR, ".sc-1t1b4cp-0.sc-1t1b4cp-1").text
                    passes = listing.find_element(By.CSS_SELECTOR, ".sc-1t1b4cp-11.sc-1t1b4cp-13").text
                    
                    # Use find_elements to safely attempt to retrieve rating elements
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
                    logging.warning(f"Error scraping listing: {e}", exc_info=True)


            # Scroll to bottom to load more listings
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)  # Allow time for new listings to load

            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height

        logging.info(f"Total listings scraped: {len(listings)}")
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

    # Define the specific order of fields/columns
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
        print(f"\nScraping complete. Data saved to '{csv_file}'.")
    except Exception as e:
        logging.error(f"Error writing data to CSV: {e}", exc_info=True)

####################################################################
# Run the Scraper
####################################################################

if __name__ == "__main__":
    main()
