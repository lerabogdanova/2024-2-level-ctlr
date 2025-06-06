"""
Crawler implementation.
"""
import datetime
import json

# pylint: disable=too-many-arguments, too-many-instance-attributes, unused-import, undefined-variable, unused-argument
import pathlib
import shutil
from typing import Pattern, Union

import requests
from bs4 import BeautifulSoup

from core_utils.article.article import Article
from core_utils.article.io import to_meta, to_raw
from core_utils.config_dto import ConfigDTO
from core_utils.constants import ASSETS_PATH, CRAWLER_CONFIG_PATH


class IncorrectSeedURLError(Exception):
    """Raised when seed URL does not match standard pattern."""


class NumberOfArticlesOutOfRangeError(Exception):
    """Raised when total number of articles is out of range from 1 to 150."""


class IncorrectNumberOfArticlesError(Exception):
    """Raised when total number of articles to parse is not integer or less than 0."""


class IncorrectHeadersError(Exception):
    """Raised when headers are not in a form of dictionary."""


class IncorrectEncodingError(Exception):
    """Raised when encoding is not specified as a string."""


class IncorrectTimeoutError(Exception):
    """Raised when timeout value is not a positive integer less than 60."""


class IncorrectVerifyError(Exception):
    """Raised when verify certificate value is not True or False."""


class Config:
    """
    Class for unpacking and validating configurations.
    """

    def __init__(self, path_to_config: pathlib.Path) -> None:
        """
        Initialize an instance of the Config class.

        Args:
            path_to_config (pathlib.Path): Path to configuration.
        """
        self.path_to_config = path_to_config
        config = self._extract_config_content()
        self._seed_urls = config.seed_urls
        self._headers = config.headers
        self._num_articles = config.total_articles
        self._timeout = config.timeout
        self._encoding = config.encoding
        self._headless_mode = config.headless_mode
        self._should_verify_certificate = config.should_verify_certificate
        self._validate_config_content()

    def _extract_config_content(self) -> ConfigDTO:
        """
        Get config values.

        Returns:
            ConfigDTO: Config values
        """
        with open(self.path_to_config, encoding="utf-8") as config_file:
            config_content = json.load(config_file)
        return ConfigDTO(**config_content)

    def _validate_config_content(self) -> None:
        """
        Ensure configuration parameters are not corrupt.
        """
        if (not isinstance(self._seed_urls, list) or not all(
            isinstance(url, str) and url.startswith("https://otr-online.ru/")
            for url in self._seed_urls
        )):
            raise IncorrectSeedURLError("Seed URLs have wrong format")

        if (not isinstance(self._num_articles, int) or
                isinstance(self._num_articles, bool) or
                self._num_articles < 0):
            raise IncorrectNumberOfArticlesError(
                "Number of articles has wrong format or number of articles < 0")

        if self._num_articles > 150:
            raise NumberOfArticlesOutOfRangeError("Number of articles is out of range")

        if not isinstance(self._headers, dict):
            raise IncorrectHeadersError("Headers must be a dict")

        if not isinstance(self._encoding, str):
            raise IncorrectEncodingError("Encoding must be a string")

        if not isinstance(self._timeout, int) or not 0 < self._timeout <= 60:
            raise IncorrectTimeoutError("Timeout has wrong format or timeout is out of range")

        if not isinstance(self._should_verify_certificate, bool):
            raise IncorrectVerifyError('Verify certificate value must either be True or False')

        if not isinstance(self._headless_mode, bool):
            raise IncorrectVerifyError('Headless mode value must either be True or False')

    def get_seed_urls(self) -> list[str]:
        """
        Retrieve seed urls.

        Returns:
            list[str]: Seed urls
        """
        return self._seed_urls

    def get_num_articles(self) -> int:
        """
        Retrieve total number of articles to scrape.

        Returns:
            int: Total number of articles to scrape
        """
        return self._num_articles

    def get_headers(self) -> dict[str, str]:
        """
        Retrieve headers to use during requesting.

        Returns:
            dict[str, str]: Headers
        """
        return self._headers

    def get_encoding(self) -> str:
        """
        Retrieve encoding to use during parsing.

        Returns:
            str: Encoding
        """
        return self._encoding

    def get_timeout(self) -> int:
        """
        Retrieve number of seconds to wait for response.

        Returns:
            int: Number of seconds to wait for response
        """
        return self._timeout

    def get_verify_certificate(self) -> bool:
        """
        Retrieve whether to verify certificate.

        Returns:
            bool: Whether to verify certificate or not
        """
        return self._should_verify_certificate

    def get_headless_mode(self) -> bool:
        """
        Retrieve whether to use headless mode.

        Returns:
            bool: Whether to use headless mode or not
        """
        return self._headless_mode


def make_request(url: str, config: Config) -> requests.models.Response:
    """
    Deliver a response from a request with given configuration.

    Args:
        url (str): Site url
        config (Config): Configuration

    Returns:
        requests.models.Response: A response from a request
    """
    request = requests.get(url, headers=config.get_headers(),
                           timeout=config.get_timeout(), verify=config.get_verify_certificate())
    request.encoding = config.get_encoding()
    return request


class Crawler:
    """
    Crawler implementation.
    """

    #: Url pattern
    url_pattern: Union[Pattern, str]

    def __init__(self, config: Config) -> None:
        """
        Initialize an instance of the Crawler class.

        Args:
            config (Config): Configuration
        """
        self.urls = []
        self.config = config

    def _extract_url(self, article_bs: BeautifulSoup) -> str:
        """
        Find and retrieve url from HTML.

        Args:
            article_bs (bs4.BeautifulSoup): BeautifulSoup instance

        Returns:
            str: Url from HTML
        """
        article_link = article_bs.find('a')
        if article_link and 'href' in article_link.attrs:
            url = article_link['href']
            if not url.startswith('http'):
                return f'https://otr-online.ru{url}'
            return url
        return "EXTRACTION ERROR"

    def find_articles(self) -> None:
        """
        Find articles.
        """
        for seed_url in self.get_search_urls():
            response = make_request(seed_url, self.config)
            if not response or response.status_code > 400:
                continue

            soup = BeautifulSoup(response.text, 'lxml')
            max_url_attempts = self.config.get_num_articles() * 2
            url_attempts = 0
            for i in self.get_search_urls():
                query = make_request(i, self.config)
                if not query.ok:
                    continue
                while (len(self.urls) < self.config.get_num_articles() and
                       url_attempts < max_url_attempts):
                    link = self._extract_url(soup)
                    if link == "EXTRACTION ERROR":
                        url_attempts += 1
                        continue
                    if link not in self.urls:
                        self.urls.append(link)
                    url_attempts += 1
                if len(self.urls) >= self.config.get_num_articles():
                    break

    def get_search_urls(self) -> list:
        """
        Get seed_urls param.

        Returns:
            list: seed_urls param
        """
        return self.config.get_seed_urls()

# 10
# 4, 6, 8, 10

class HTMLParser:
    """
    HTMLParser implementation.
    """

    def __init__(self, full_url: str, article_id: int, config: Config) -> None:
        """
        Initialize an instance of the HTMLParser class.

        Args:
            full_url (str): Site url
            article_id (int): Article id
            config (Config): Configuration
        """
        self.full_url = full_url
        self.article_id = article_id
        self.config = config
        self.article = Article(url=full_url, article_id=article_id)

    def _fill_article_with_text(self, article_soup: BeautifulSoup) -> None:
        """
        Find text of article.

        Args:
            article_soup (bs4.BeautifulSoup): BeautifulSoup instance
        """
        div_body = article_soup.find_all("div")
        if div_body:
            texts = []
            for p in div_body:
                texts.append(p.get_text())
            self.article.text = "\n".join(texts)
        else:
            self.article.text = "NOT FOUND"

    def _fill_article_with_meta_information(self, article_soup: BeautifulSoup) -> None:
        """
        Find meta information of article.

        Args:
            article_soup (bs4.BeautifulSoup): BeautifulSoup instance
        """
        title = article_soup.find("title")
        self.article.title = title.get_text()

        author_tag = article_soup.find("itemprop", class_='author')
        self.article.author = [author_tag.get_text(strip=True)] if author_tag else ["NOT FOUND"]

    def unify_date_format(self, date_str: str) -> datetime.datetime:
        """
        Unify date format.

        Args:
            date_str (str): Date in text format

        Returns:
            datetime.datetime: Datetime object
        """

    def parse(self) -> Union[Article, bool, list]:
        """
        Parse each article.

        Returns:
            Union[Article, bool, list]: Article instance
        """
        response = make_request(self.full_url, self.config)
        response.encoding = "utf-8"
        if response.ok:
            soup = BeautifulSoup(response.text, "lxml")
            self._fill_article_with_text(soup)
            self._fill_article_with_meta_information(soup)
        return self.article


def prepare_environment(base_path: Union[pathlib.Path, str]) -> None:
    """
    Create ASSETS_PATH folder if no created and remove existing folder.

    Args:
        base_path (Union[pathlib.Path, str]): Path where articles stores
    """
    if pathlib.Path(base_path).is_dir():
        shutil.rmtree(base_path)
    pathlib.Path(base_path).mkdir(parents=True)


def main() -> None:
    """
    Entrypoint for scrapper module.
    """
    configuration = Config(path_to_config=CRAWLER_CONFIG_PATH)
    prepare_environment(ASSETS_PATH)
    crawler = Crawler(config=configuration)
    crawler.find_articles()

    for index, url in enumerate(crawler.urls):
        parser = HTMLParser(full_url=url, article_id=index + 1, config=configuration)
        article_info = parser.parse()

        if isinstance(article_info, Article):
            to_raw(article_info)
            to_meta(article_info)


if __name__ == "__main__":
    main()
