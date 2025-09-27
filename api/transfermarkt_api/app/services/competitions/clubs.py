from dataclasses import dataclass

from app.services.base import TransfermarktBase
from app.utils.utils import extract_from_url
from app.utils.xpath import Competitions


@dataclass
class TransfermarktCompetitionClubs(TransfermarktBase):
    """
    A class for retrieving and parsing the list of football clubs in a specific competition on Transfermarkt.

    Args:
        competition_id (str): The unique identifier of the competition.
        season_id (str): The season identifier. If not provided, it will be extracted from the URL.
        URL (str): The URL template for the competition's page on Transfermarkt.
    """

    competition_id: str = None
    season_id: str = None
    URL: str = "https://www.transfermarkt.com/-/startseite/wettbewerb/{competition_id}/plus/?saison_id={season_id}"

    def __post_init__(self) -> None:
        """Initialize the TransfermarktCompetitionClubs class."""
        self.URL = self.URL.format(competition_id=self.competition_id, season_id=self.season_id)
        self.page = self.request_url_page()
        self.raise_exception_if_not_found(xpath=Competitions.Profile.NAME)

    def __parse_competition_clubs(self) -> list:
        """
        Parse the competition's page and extract information about the football clubs participating
            in the competition.

        Returns:
            list: A list of dictionaries, where each dictionary contains information about a
                football club in the competition, including the club's unique identifier and name.
        """
        urls = self.get_list_by_xpath(Competitions.Clubs.URLS)
        names = self.get_list_by_xpath(Competitions.Clubs.NAMES)
        ids = [extract_from_url(url) for url in urls]

        return [{"id": idx, "name": name} for idx, name in zip(ids, names) if idx and name]

    def __build_fallback_urls(self) -> list[str]:
        base_urls = [
            "https://www.transfermarkt.com/-/teilnehmer/wettbewerb/{competition_id}",
            "https://www.transfermarkt.com/-/teilnehmer/pokalwettbewerb/{competition_id}",
        ]

        formatted_urls = []
        for url in base_urls:
            formatted = url.format(competition_id=self.competition_id)
            if self.season_id:
                separator = "&" if "?" in formatted else "?"
                formatted = f"{formatted}{separator}saison_id={self.season_id}"
            formatted_urls.append(formatted)

        return formatted_urls

    def __parse_competition_clubs_with_fallback(self) -> list:
        clubs = self.__parse_competition_clubs()
        if len(clubs) > 4:
            return clubs

        original_page = self.page
        best_clubs = clubs

        for url in self.__build_fallback_urls():
            try:
                fallback_page = self.request_url_page(url=url)
            except Exception:
                continue

            fallback_clubs: list = []
            try:
                self.page = fallback_page
                fallback_clubs = self.__parse_competition_clubs()
            finally:
                self.page = original_page

            if len(fallback_clubs) > len(best_clubs):
                best_clubs = fallback_clubs

            if len(best_clubs) > 4:
                break

        return best_clubs

    def get_competition_clubs(self) -> dict:
        """
        Retrieve and parse the list of football clubs participating in a specific competition.

        Returns:
            dict: A dictionary containing the competition's unique identifier, name, season identifier, list of clubs
                  participating in the competition, and the timestamp of when the data was last updated.
        """
        self.response["id"] = self.competition_id
        self.response["name"] = self.get_text_by_xpath(Competitions.Profile.NAME)
        season_links = self.get_list_by_xpath(Competitions.Profile.URL, remove_empty=False)
        season_id = None
        for link in season_links:
            season_id = extract_from_url(link, "season_id")
            if season_id:
                break

        if not season_id:
            season_id = extract_from_url(self.URL, "season_id")

        self.response["seasonId"] = season_id or (self.season_id or "")
        self.response["clubs"] = self.__parse_competition_clubs_with_fallback()

        return self.response
