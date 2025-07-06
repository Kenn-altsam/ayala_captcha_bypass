import pandas as pd
from datetime import datetime
import os
import time
from dotenv import load_dotenv
from captcha_bypass import solve_captcha, status
import logging
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import psycopg2
from selenium.common.exceptions import TimeoutException

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constants
CSV_FILE = 'companies_data.csv'

class TaxDataScraper:
    def __init__(self):
        # Load .env variables (e.g. DB credentials)
        load_dotenv()

        self.url = "https://kgd.gov.kz/ru/services/taxpayer_search/legal_entity"
        self.companies = self.load_existing_data()

        # Initialise database connection
        self.init_db()
        
    def load_existing_data(self):
        """Load existing data from CSV if it exists"""
        try:
            if os.path.exists(CSV_FILE):
                df = pd.read_csv(CSV_FILE)
                # Убедимся, что колонка БИН имеет строковый тип, чтобы избежать проблем с ведущими нулями
                if 'bin' in df.columns:
                    df['bin'] = df['bin'].astype(str)
                return df.to_dict('records')
            return []
        except Exception as e:
            logger.error(f"Error loading existing data: {e}")
            return []
            
    def save_to_csv(self):
        """Save data to CSV file"""
        try:
            if not self.companies:
                logger.info("No data to save to CSV.")
                return
            df = pd.DataFrame(self.companies)
            df.to_csv(CSV_FILE, index=False, encoding='utf-8-sig')  # utf-8-sig для корректного отображения в Excel
            logger.info(f"Data for {len(self.companies)} companies saved to {CSV_FILE}")
        except Exception as e:
            logger.error(f"Error saving data to CSV: {e}")
            
    def init_browser(self):
        """Initialize browser"""
        logger.info("Initializing browser...")
        options = webdriver.ChromeOptions()
        # options.add_argument('--headless')  # Можно включить для работы в фоновом режиме
        options.add_argument('--start-maximized')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--log-level=3')  # Убирает лишние логи Selenium
        options.add_experimental_option('excludeSwitches', ['enable-logging'])

        # Чтобы браузер не закрывался сразу (для отладки)
        # options.add_experimental_option('detach', True)

        self.driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        self.wait = WebDriverWait(self.driver, 20)
        logger.info("Browser initialized.")
        
    def close_browser(self):
        """Close browser and DB connection"""
        if hasattr(self, 'driver') and self.driver:
            self.driver.quit()
            logger.info("Browser closed.")
        # Ensure we also close DB connection
        self.close_db()
        
    def parse_money_value(self, value):
        """Convert string money value to float"""
        try:
            return float(value.replace(' ', '').replace(',', '.') or 0)
        except (ValueError, AttributeError):
            return 0.0
            
    def parse_date(self, date_str):
        """Convert date string to database format"""
        if not date_str or not date_str.strip():
            return None
        try:
            return datetime.strptime(date_str.strip(), '%d.%m.%Y').strftime('%Y-%m-%d')
        except ValueError:
            return None
            
    def extract_all_data(self):
        """Извлекает данные о компании и налогах со страницы результатов."""
        try:
            # Ждем появления контейнера с результатами
            self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'div.results')))

            # --- Извлечение данных о компании (первая таблица) ---
            info_table = self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'table.table-bordered')))
            rows = info_table.find_elements(By.CSS_SELECTOR, 'tbody tr')
            if not rows:
                return None

            cells = rows[0].find_elements(By.TAG_NAME, 'td')
            company_data = {
                'bin': cells[4].text.strip(),
                'name': cells[1].text.strip(),
                'company_type': cells[2].text.strip(),
                'rnn': cells[3].text.strip(),
                'registered_at': self.parse_date(cells[5].text.strip())
            }

            # --- Извлечение данных о налогах (вторая таблица) ---
            tax_table = self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'table.table-taxpayment')))
            tax_rows = tax_table.find_elements(By.CSS_SELECTOR, 'tbody tr')

            # Инициализируем поля
            for year in range(2020, 2025):
                company_data[f'tax_payment_{year}'] = 0.0
                company_data[f'vat_refund_{year}'] = 0.0

            for row in tax_rows:
                cells = row.find_elements(By.TAG_NAME, 'td')
                row_type = cells[0].text.strip()

                if 'Налоговые поступления' in row_type:
                    for year, cell in zip(range(2020, 2025), cells[1:]):
                        company_data[f'tax_payment_{year}'] = self.parse_money_value(cell.text)
                elif 'сумма возврата превышения НДС' in row_type:
                    for year, cell in zip(range(2020, 2025), cells[1:]):
                        company_data[f'vat_refund_{year}'] = self.parse_money_value(cell.text)

            return company_data

        except TimeoutException:
            # Проверяем, не появилось ли сообщение "ничего не найдено"
            try:
                not_found_msg = self.driver.find_element(By.XPATH, "//*[contains(text(), 'По вашему запросу ничего не найдено')]")
                if not_found_msg:
                    logger.warning("Company not found on the portal.")
                    return "NOT_FOUND"
            except Exception:
                logger.error("Timed out waiting for results, and no 'not found' message was detected.")
                return None
        except Exception as e:
            logger.error(f"Error extracting data: {e}")
            return None
            
    def update_company_data(self, company_data):
        """Update or add company data to the list"""
        # Check if company already exists
        for i, company in enumerate(self.companies):
            if company['bin'] == company_data['bin']:
                self.companies[i] = company_data
                return
                
        # Add new company if limit not reached
        self.companies.append(company_data)
            
    def scrape_tax_data(self, bin_list):
        """Main function to scrape tax data"""
        self.init_browser()
        try:
            for bin_number in bin_list:
                logger.info(f"--- Processing BIN: {bin_number} ---")
                try:
                    self.driver.get(self.url)

                    # 1. Ввести БИН
                    logger.info("Entering BIN...")
                    bin_input = self.wait.until(EC.element_to_be_clickable((By.ID, "edit-uin-biniin-1")))
                    bin_input.clear()
                    bin_input.send_keys(bin_number)

                    # 2. Решить капчу
                    logger.info("Solving CAPTCHA...")
                    captcha_result, _ = solve_captcha(self.driver)

                    if captcha_result != status.SUCCESS:
                        logger.error(f"Failed to solve CAPTCHA for BIN {bin_number}. Status: {captcha_result.name}")
                        continue

                    logger.info("CAPTCHA solved successfully.")

                    # 3. Нажать кнопку "Поиск"
                    logger.info("Clicking search button...")
                    # Ждем, пока капча обработается и кнопка станет кликабельной
                    time.sleep(2)
                    search_button = self.wait.until(EC.element_to_be_clickable((By.ID, "edit-submit-1")))
                    search_button.click()

                    # 4. Извлечь данные
                    logger.info("Extracting data from results page...")
                    company_data = self.extract_all_data()

                    if company_data and company_data != "NOT_FOUND":
                        self.update_company_data(company_data)
                        self.save_company_to_db(company_data)
                        logger.info(f"Successfully processed and saved data for BIN: {bin_number}")
                    elif company_data == "NOT_FOUND":
                        logger.warning(f"No data found on the portal for BIN: {bin_number}")
                    else:
                        logger.error(f"Failed to extract data for BIN: {bin_number}")

                    # Сохраняем в CSV после каждой успешной записи
                    self.save_to_csv()

                except Exception as e:
                    logger.error(f"A critical error occurred while processing BIN {bin_number}: {e}")
                    # Сделаем скриншот для отладки
                    try:
                        self.driver.save_screenshot(f'error_screenshot_{bin_number}.png')
                    except Exception as ss_e:
                        logger.error(f"Failed to save screenshot: {ss_e}")
                    continue

        finally:
            self.close_browser()
            logger.info("Scraping process finished.")

    # ------------------------------------------------------------------
    # Database helpers
    # ------------------------------------------------------------------

    def init_db(self):
        """Initialise PostgreSQL connection and ensure `companies` table exists"""
        try:
            db_url = os.getenv("DATABASE_URL")
            if db_url:
                # Allow full connection URI, e.g. postgresql://user:pass@host:port/db
                self.conn = psycopg2.connect(db_url)
            else:
                self.conn = psycopg2.connect(
                    host=os.getenv("DB_HOST", "localhost"),
                    port=int(os.getenv("DB_PORT", 5432)),
                    dbname=os.getenv("DB_NAME", "Ayala_database"),
                    user=os.getenv("DB_USER", "postgres"),
                    password=os.getenv("DB_PASSWORD", "")
                )
            self.cursor = self.conn.cursor()

            create_table_sql = """
            CREATE TABLE IF NOT EXISTS companies (
                bin VARCHAR(12) PRIMARY KEY,
                name TEXT,
                company_type TEXT,
                rnn TEXT,
                registered_at DATE,
                tax_payment_2020 NUMERIC,
                tax_payment_2021 NUMERIC,
                tax_payment_2022 NUMERIC,
                tax_payment_2023 NUMERIC,
                tax_payment_2024 NUMERIC,
                vat_refund_2020 NUMERIC,
                vat_refund_2021 NUMERIC,
                vat_refund_2022 NUMERIC,
                vat_refund_2023 NUMERIC,
                vat_refund_2024 NUMERIC
            );
            """
            self.cursor.execute(create_table_sql)
            self.conn.commit()
            logger.info("Database connection initialized.")
        except Exception as e:
            logger.error(f"Error connecting to database: {e}")
            self.conn = None
            self.cursor = None

    def save_company_to_db(self, company_data):
        """Insert or update a single company row in the database"""
        if not getattr(self, "cursor", None):
            return

        try:
            upsert_sql = """
            INSERT INTO companies (bin, name, company_type, rnn, registered_at,
                tax_payment_2020, tax_payment_2021, tax_payment_2022, tax_payment_2023, tax_payment_2024,
                vat_refund_2020, vat_refund_2021, vat_refund_2022, vat_refund_2023, vat_refund_2024)
            VALUES (%(bin)s, %(name)s, %(company_type)s, %(rnn)s, %(registered_at)s,
                %(tax_payment_2020)s, %(tax_payment_2021)s, %(tax_payment_2022)s, %(tax_payment_2023)s, %(tax_payment_2024)s,
                %(vat_refund_2020)s, %(vat_refund_2021)s, %(vat_refund_2022)s, %(vat_refund_2023)s, %(vat_refund_2024)s)
            ON CONFLICT (bin) DO UPDATE SET
                name = EXCLUDED.name,
                company_type = EXCLUDED.company_type,
                rnn = EXCLUDED.rnn,
                registered_at = EXCLUDED.registered_at,
                tax_payment_2020 = EXCLUDED.tax_payment_2020,
                tax_payment_2021 = EXCLUDED.tax_payment_2021,
                tax_payment_2022 = EXCLUDED.tax_payment_2022,
                tax_payment_2023 = EXCLUDED.tax_payment_2023,
                tax_payment_2024 = EXCLUDED.tax_payment_2024,
                vat_refund_2020 = EXCLUDED.vat_refund_2020,
                vat_refund_2021 = EXCLUDED.vat_refund_2021,
                vat_refund_2022 = EXCLUDED.vat_refund_2022,
                vat_refund_2023 = EXCLUDED.vat_refund_2023,
                vat_refund_2024 = EXCLUDED.vat_refund_2024;
            """
            self.cursor.execute(upsert_sql, company_data)
            self.conn.commit()
            logger.info(f"Data for BIN {company_data['bin']} saved to DB.")
        except Exception as e:
            logger.error(f"Error saving data to database: {e}")
            if self.conn:
                self.conn.rollback()

    def close_db(self):
        """Close database connection cleanly"""
        if getattr(self, "cursor", None):
            self.cursor.close()
        if getattr(self, "conn", None):
            self.conn.close()
        logger.info("Database connection closed.")

def main():
    # Example BIN numbers
    bin_list = [
        "930340000589",  # Example from the provided data
        # Add more BIN numbers here
    ]
    
    scraper = TaxDataScraper()
    scraper.scrape_tax_data(bin_list)

if __name__ == "__main__":
    main() 