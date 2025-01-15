import time
import csv
import logging
import json
import sys

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

# We'll limit how many total events we process for demonstration.
MAX_EVENTS = 8  

####################################################################
# Utility / Helper Functions
####################################################################

def safe_click(el):
    """Attempt to click an element with extra safety."""
    try:
        el.click()
    except (ElementClickInterceptedException, ElementNotInteractableException) as e:
        logging.warning(f"Could not click element: {e}")

def wait_for_overlay_to_disappear(driver, overlay_selector=""):
    """
    If your site uses a known overlay or spinner, add a CSS or XPATH here.
    We'll wait for it to vanish. If none is known, you can skip this step.
    """
    if not overlay_selector:
        return  # no known overlay
    try:
        # Wait for overlay to appear
        WebDriverWait(driver, 3).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, overlay_selector))
        )
        # Wait for overlay to vanish
        WebDriverWait(driver, 10).until_not(
            EC.visibility_of_element_located((By.CSS_SELECTOR, overlay_selector))
        )
        logging.info("Overlay disappeared; safe to proceed.")
    except TimeoutException:
        pass

def robust_click_continue_button(driver, timeout=15):
    """
    1) Check if we already auto-forwarded to the price page
       (the 'ticketPrice_non_decimal' input is present).
    2) If not, wait for & click 'Continue'.
    """
    try:
        WebDriverWait(driver, 2).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, "input[name='ticketPrice_non_decimal']"))
        )
        logging.info("Auto-forwarded to price page; skipping 'Continue' click.")
        return
    except TimeoutException:
        pass

    wait_for_overlay_to_disappear(driver, overlay_selector="")

    try:
        cbtn = WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((By.XPATH, "//button[normalize-space()='Continue']"))
        )
        safe_click(cbtn)
        logging.info("Clicked 'Continue' after seat selection.")
    except TimeoutException:
        logging.error("Timeout waiting for 'Continue' after seat selection.")
    except Exception as e:
        logging.error(f"Error clicking 'Continue': {e}", exc_info=True)

####################################################################
# Main Scraping Logic
####################################################################

def main():
    logging.info("=== Starting StubHub Scraper ===")

    options = webdriver.ChromeOptions()
    # Uncomment if you want headless:
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

        # Scrape events twice with a delay
        time.sleep(5)
        events_first_round = scrape_events(driver)

        time.sleep(5)
        events_second_round = scrape_events(driver)

        # Merge/dedupe
        final_events = merge_and_deduplicate_events(events_first_round, events_second_round)
        final_events = [evt for evt in final_events if not is_na_event(evt)]

        logging.info("Merged final events after deduplication and removing 'N/A':\n" +
                     json.dumps(final_events, indent=2))
        print(f"Total final events to process: {len(final_events)}")

        all_data_rows = []
        event_count = 0

        for idx, evt in enumerate(final_events):
            if MAX_EVENTS and event_count >= MAX_EVENTS:
                logging.info("Reached MAX_EVENTS limit; stopping event processing.")
                break

            logging.info(f"Processing event #{idx + 1}: {evt}")
            rows = process_event(driver, evt, idx)
            all_data_rows.extend(rows)
            event_count += 1

        # Write CSV
        write_data_to_csv(all_data_rows, OUTPUT_CSV_FILE)

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
        logging.error("Timeout waiting for manual login.")
        print("Login timeout exceeded. Please try again.")
        driver.quit()
        sys.exit(1)

def close_popups(driver):
    logging.info("Attempting to close any pop-ups.")
    try:
        popups = driver.find_elements(By.XPATH, "//button[@aria-label='Close']")
        for p in popups:
            safe_click(p)
            logging.info("Closed a pop-up.")
    except Exception:
        logging.debug("No pop-ups to close or error closing pop-ups.")

    # Check for captcha
    try:
        driver.find_element(By.XPATH, "//iframe[contains(@src, 'captcha')]")
        logging.error("Captcha detected. Cannot proceed.")
    except NoSuchElementException:
        logging.info("No captcha detected.")

def go_to_sell(driver):
    logging.info("Navigating to 'Sell Tickets' page.")
    try:
        driver.get("https://www.stubhub.com/sell")
        time.sleep(3)
        logging.info("Arrived at Sell page.")
    except Exception as e:
        logging.error(f"Error navigating to Sell tickets: {e}", exc_info=True)

def search_location(driver, location_query):
    logging.info(f"Searching for location: {location_query}")
    try:
        close_popups(driver)

        inp = WebDriverWait(driver, DEFAULT_TIMEOUT).until(
            EC.element_to_be_clickable((By.XPATH, "//input[@placeholder='Search your event and start selling']"))
        )
        inp.clear()
        inp.send_keys(location_query)
        inp.send_keys(Keys.ENTER)
        time.sleep(4)
        logging.info(f"Location '{location_query}' searched successfully.")
    except Exception as e:
        logging.error(f"Error searching location: {e}", exc_info=True)

def navigate_to_parking_tab(driver):
    logging.info("Navigating to 'Parking' tab.")
    try:
        parking_btn = WebDriverWait(driver, DEFAULT_TIMEOUT).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Parking')]"))
        )
        safe_click(parking_btn)
        time.sleep(3)
        logging.info("Successfully navigated to 'Parking' tab.")
    except Exception as e:
        logging.error(f"Error navigating to 'Parking' tab: {e}", exc_info=True)

def scrape_events(driver):
    logging.info("Starting to scrape event details.")
    try:
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CLASS_NAME, "sc-1pn28cb-0"))
        )
        cards = driver.find_elements(By.CLASS_NAME, "sc-1or4et4-0")
        if not cards:
            logging.warning("No events found.")
            return []

        result = []
        for i, c in enumerate(cards):
            date = time_txt = name = location = "N/A"
            # Date
            try:
                date = c.find_element(By.CLASS_NAME, "sc-yi86cf-2").text
            except:
                pass
            # Time => the last .sc-ntazun-5 is often the actual time
            try:
                times = c.find_elements(By.CLASS_NAME, "sc-ntazun-5")
                if times:
                    time_txt = times[-1].text
            except:
                pass
            # Name
            try:
                name = c.find_element(By.CLASS_NAME, "sc-18gjf30-0").text
            except:
                pass
            # Location
            try:
                location = c.find_element(By.CLASS_NAME, "sc-ntazun-30").text
            except:
                pass

            item = {
                "date": date,
                "time": time_txt,
                "name": name,
                "location": location
            }
            logging.info(f"Scraped event: {item}")
            result.append(item)

        logging.info(f"Total events scraped: {len(result)}")
        return result
    except Exception as e:
        logging.error(f"Error scraping events: {e}", exc_info=True)
        return []

def merge_and_deduplicate_events(ev1, ev2):
    merged = ev1 + ev2
    seen = set()
    unique_events = []
    for e in merged:
        key = (e.get("date",""), e.get("time",""), e.get("name",""), e.get("location",""))
        if key not in seen:
            seen.add(key)
            unique_events.append(e)
    return unique_events

def is_na_event(evt):
    """If the event's name is N/A, treat it as worthless."""
    return (evt.get("name","N/A") == "N/A")

def process_event(driver, event_details, event_index):
    """
    1) Re-locate event cards; find 'Sell Tickets' -> click
    2) Possibly new tab or same tab
    3) do_quantity_and_ticket_type
    4) scrape seats => each seat => seat->price->compare->close compare->back->seat
    5) close event tab or back to listing
    """
    data_rows = []

    event_cards = driver.find_elements(By.CLASS_NAME, "sc-1or4et4-0")
    if event_index >= len(event_cards):
        logging.error(f"Event index {event_index} out of range (total {len(event_cards)}).")
        return data_rows

    # Sell button inside the card
    try:
        card = event_cards[event_index]
        sell_btn = card.find_element(By.CSS_SELECTOR, ".sc-ntazun-15.DTcPk")
    except NoSuchElementException:
        logging.warning("Could not find 'Sell Tickets' button in the card.")
        return data_rows

    original_handles = driver.window_handles
    original_url = driver.current_url

    safe_click(sell_btn)
    logging.info(f"Clicked on the event at index {event_index + 1}.")

    # Wait for a new tab or URL change
    try:
        WebDriverWait(driver, 10).until(
            lambda d: len(d.window_handles) > len(original_handles) or d.current_url != original_url
        )
    except TimeoutException:
        logging.error(f"No new tab/URL change for event index {event_index+1}.")
        return data_rows

    # If new tab opened, switch
    all_handles = driver.window_handles
    if len(all_handles) > len(original_handles):
        new_event_tab = [h for h in all_handles if h not in original_handles][0]
        driver.switch_to.window(new_event_tab)
        logging.info("Switched to new event tab.")
    else:
        logging.info("Event opened in the same tab.")

    # do quantity/ticket type
    if not do_quantity_and_ticket_type(driver):
        logging.warning("Could not complete ticket quantity/type steps.")
        # If we opened a new event tab, close it
        if len(driver.window_handles) > len(original_handles):
            driver.close()
            driver.switch_to.window(original_handles[0])
        return data_rows

    # Now on seat dropdown page
    seat_labels = scrape_all_seats_options(driver)
    for seat_label in seat_labels:
        seat_label = seat_label.strip()
        if not seat_label:
            logging.info("Skipping blank seat label from dropdown.")
            continue

        logging.info(f"Processing seat: {seat_label}")
        seat_data = process_seat_flow(driver, seat_label, event_details)
        data_rows.extend(seat_data)

    # After all seats, if new event tab, close it or else go back
    if len(driver.window_handles) > len(original_handles):
        driver.close()
        driver.switch_to.window(original_handles[0])
        logging.info("Closed the event tab and switched back to main listing.")
    else:
        logging.info("Using same tab; navigating back to listing.")
        driver.back()
        time.sleep(2)

    return data_rows

def do_quantity_and_ticket_type(driver):
    """1 Ticket -> Continue -> E-Tickets -> (opt) I'll upload later -> Continue"""
    try:
        WebDriverWait(driver, 30).until(
            EC.visibility_of_element_located((By.XPATH, "//div[contains(text(), 'How many tickets do you have?')]"))
        )
        dd = WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'select[name="quantity"]'))
        )
        Select(dd).select_by_visible_text("1 Ticket")
        logging.info("Selected 1 ticket.")

        first_btn = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.CLASS_NAME, "sc-6f7nfk-0"))
        )
        safe_click(first_btn)
        logging.info("Clicked first Continue.")

        second_btn = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.XPATH, "//form[@novalidate]//button[normalize-space()='Continue' and not(@disabled)]"))
        )
        safe_click(second_btn)
        logging.info("Clicked second Continue.")

        WebDriverWait(driver, 20).until(
            EC.visibility_of_element_located((By.XPATH, "//div[contains(text(), 'What type of tickets are you listing?')]"))
        )
        e_tix = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.XPATH, "//label[.//span[contains(text(),'E-Tickets')]]//input[@type='Radio']"))
        )
        safe_click(e_tix)
        logging.info("Selected E-Tickets.")

        # optional "I'll upload later"
        try:
            up_later = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//label[.//span[contains(text(), \"I'll upload later\")]]"))
            )
            safe_click(up_later)
            logging.info("Selected 'I'll upload later'.")
        except TimeoutException:
            logging.warning("No 'I'll upload later' found.")

        final_btn = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.XPATH, "//button[normalize-space()='Continue' and not(@disabled)]"))
        )
        safe_click(final_btn)
        logging.info("Clicked final Continue.")
        return True
    except Exception as e:
        logging.error(f"Error in do_quantity_and_ticket_type: {e}", exc_info=True)
        return False

def scrape_all_seats_options(driver):
    """
    Return seat labels from the seat dropdown. Some sites have a blank first option, which we'll collect but skip later.
    """
    seat_labels = []
    try:
        seat_dd = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".css-13jwkg0-control"))
        )
        arrow = seat_dd.find_element(By.CSS_SELECTOR, ".css-1og4hos-indicatorContainer")
        safe_click(arrow)

        options = WebDriverWait(driver, 10).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div[class*='menu'] div"))
        )
        seat_labels = [o.text for o in options]
        safe_click(arrow)

        logging.info(f"Found seat options: {seat_labels}")
    except TimeoutException:
        logging.warning("No seat dropdown or seat options found.")
    except Exception as e:
        logging.error(f"Error scraping seats dropdown: {e}", exc_info=True)
    return seat_labels

def process_seat_flow(driver, seat_label, event_details):
    """
    1) Re-open seat dropdown, select seat_label
    2) robust_click_continue_button => lands on Price Page
    3) Compare => new tab => scrape => close => come back to Price Page
    4) driver.back() => seat dropdown for next seat
    """
    rows = []

    # 1) select seat
    if not select_seat_option(driver, seat_label):
        return rows  # seat selection failed

    # 2) click Continue => Price Page
    robust_click_continue_button(driver, timeout=15)

    # 3) On the Price Page, open 'Compare' => new tab => scrape => close => back to Price Page
    price_tab = driver.current_window_handle
    price, listings = interact_with_ticket_price_page(driver, price_tab)
    for listing in listings:
        row = {
            "event_date": event_details.get("date", ""),
            "event_time": event_details.get("time", ""),
            "event_name": event_details.get("name", ""),
            "event_location": event_details.get("location", ""),
            "selected_seat": seat_label,
            "per_ticket_price": price,
            "listing_title": listing.get("title", ""),
            "listing_price": listing.get("price", ""),
            "listing_passes": listing.get("passes", ""),
            "listing_rating_score": listing.get("rating_score", ""),
            "listing_rating_label": listing.get("rating_label", ""),
        }
        rows.append(row)

    # 4) now from Price Page => driver.back() => seat dropdown
    navigate_back_to_seats(driver)
    return rows

def select_seat_option(driver, seat_label):
    """Locate seat dropdown, exact match seat_label, click it."""
    try:
        seat_dd = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".css-13jwkg0-control"))
        )
        arrow = seat_dd.find_element(By.CSS_SELECTOR, ".css-1og4hos-indicatorContainer")
        safe_click(arrow)

        options = WebDriverWait(driver, 10).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div[class*='menu'] div"))
        )

        matched = False
        for opt in options:
            if opt.text.strip() == seat_label.strip():
                safe_click(opt)
                logging.info(f"Selected seat option: {seat_label}")
                matched = True
                break

        if not matched:
            logging.warning(f"No match for seat '{seat_label}'")
            safe_click(arrow)
            return False
        return True
    except Exception as e:
        logging.error(f"Error selecting seat '{seat_label}': {e}", exc_info=True)
        return False

def interact_with_ticket_price_page(driver, price_tab_handle):
    """
    On the Price Page:
     - Wait for price input
     - Click 'Compare tickets' => new tab
     - Scrape => close => switch back to price_tab_handle
    """
    listings = []
    price_str = ""

    try:
        logging.info("Interacting with the ticket price page...")
        price_in = WebDriverWait(driver, 30).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, "input[name='ticketPrice_non_decimal']"))
        )
        price_str = price_in.get_attribute("value") or ""
        logging.info(f"Extracted per ticket price: US$ {price_str}")

        compare_link = WebDriverWait(driver, 30).until(
            EC.element_to_be_clickable((By.LINK_TEXT, "Compare similar tickets"))
        )
        logging.info("Clicking 'Compare similar tickets'.")
        old_handles = driver.window_handles
        safe_click(compare_link)

        WebDriverWait(driver, 30).until(
            lambda d: len(d.window_handles) > len(old_handles) or d.current_url != driver.current_url
        )

        if len(driver.window_handles) > len(old_handles):
            compare_tab = [h for h in driver.window_handles if h not in old_handles][0]
            driver.switch_to.window(compare_tab)
            logging.info("Switched to new Compare tab.")
        else:
            logging.info("Compare loaded in same tab (unexpected?).")

        # Scrape listings
        listings_container = WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.ID, "listings-container"))
        )
        logging.info("Listings container loaded successfully.")

        last_height = driver.execute_script("return document.body.scrollHeight")
        while True:
            new_visible = listings_container.find_elements(By.CSS_SELECTOR, ".sc-194s59m-1.ivCIjj")
            for li in new_visible[len(listings):]:
                try:
                    title = ""
                    price = ""
                    passes = ""
                    rating_score = ""
                    rating_label = ""

                    try:
                        title = li.find_element(By.CSS_SELECTOR, ".sc-1t1b4cp-0.sc-1t1b4cp-6").text
                    except:
                        pass
                    try:
                        price = li.find_element(By.CSS_SELECTOR, ".sc-1t1b4cp-0.sc-1t1b4cp-1").text
                    except:
                        pass
                    try:
                        passes = li.find_element(By.CSS_SELECTOR, ".sc-1t1b4cp-11.sc-1t1b4cp-13").text
                    except:
                        pass
                    try:
                        rating_elems = li.find_elements(By.CSS_SELECTOR, ".sc-5cv63s-3")
                        if rating_elems:
                            rating_score = rating_elems[0].text
                    except:
                        pass
                    try:
                        rating_label_elems = li.find_elements(By.CSS_SELECTOR, ".sc-5cv63s-2")
                        if rating_label_elems:
                            rating_label = rating_label_elems[0].text
                    except:
                        pass

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

            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height

        logging.info(f"Total listings scraped: {len(listings)}")

        # close compare tab if it was opened
        if driver.current_window_handle != price_tab_handle:
            driver.close()
            driver.switch_to.window(price_tab_handle)
            logging.info("Closed Compare tab, back on Price Page tab.")

    except TimeoutException as e:
        logging.error(f"Timeout on ticket price page: {e}", exc_info=True)
    except Exception as e:
        logging.error(f"Error on the ticket price page: {e}", exc_info=True)

    return price_str, listings

def navigate_back_to_seats(driver):
    """
    From Price Page => do driver.back() => seat dropdown.
    Possibly do 2 backs if needed, if seat dropdown isn't visible.
    """
    for _ in range(2):
        if seat_dropdown_visible(driver):
            logging.info("Seat dropdown already visible, no need to go back.")
            break

        driver.back()
        time.sleep(2)
        if seat_dropdown_visible(driver):
            logging.info("Back navigation success: seat dropdown is visible.")
            break
        else:
            logging.info("Still not seeing seat dropdown; going back again.")

def seat_dropdown_visible(driver):
    """Return True if the seat dropdown is visible on the page."""
    try:
        dd = driver.find_element(By.CSS_SELECTOR, ".css-13jwkg0-control")
        return dd.is_displayed()
    except NoSuchElementException:
        return False

def write_data_to_csv(final_data, csv_file):
    logging.info(f"Writing data to CSV: {csv_file}")
    if not final_data:
        logging.warning("No data to write to CSV.")
        print("No data to write to CSV.")
        return

    fields = [
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
        with open(csv_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for row in final_data:
                writer.writerow(row)
        logging.info(f"Wrote {len(final_data)} rows to CSV: {csv_file}")
        print(f"\nScraping complete. Data saved to '{csv_file}'.")
    except Exception as e:
        logging.error(f"Error writing CSV: {e}", exc_info=True)


####################################################################
# Run the Scraper
####################################################################
if __name__ == "__main__":
    main()
