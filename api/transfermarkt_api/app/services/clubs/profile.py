from dataclasses import dataclass
from typing import Optional

from app.services.base import TransfermarktBase
from app.utils.regex import REGEX_BG_COLOR, REGEX_COUNTRY_ID, REGEX_MEMBERS_DATE
from app.utils.utils import extract_from_url, remove_str, safe_regex, safe_split
from app.utils.xpath import Clubs


@dataclass
class TransfermarktClubProfile(TransfermarktBase):
    """
    A class for retrieving and parsing the profile information of a football club from Transfermarkt.

    Args:
        club_id (str): The unique identifier of the football club.
        URL (str): The URL template for the club's profile page on Transfermarkt.
    """

    club_id: str = None
    URL: str = "https://www.transfermarkt.us/-/datenfakten/verein/{club_id}"

    def __post_init__(self) -> None:
        """Initialize the TransfermarktClubProfile class."""
        self.URL = self.URL.format(club_id=self.club_id)
        self.page = self.request_url_page()
        self.raise_exception_if_not_found(xpath=Clubs.Profile.URL)

    def get_club_profile(self) -> dict:
        """
        Retrieve and parse the profile information of the football club from Transfermarkt.

        This method extracts various attributes of the club's profile, such as name, official name, address, contact
        information, stadium details, and more.

        Returns:
            dict: A dictionary containing the club's profile information.
        """
        def text_or_default(xpath: str, default: str = "") -> str:
            value = self.get_text_by_xpath(xpath)
            return value if value is not None else default

        def numeric_or_default(value: Optional[str], default: str = "0") -> str:
            if value and any(char.isdigit() for char in value):
                return value
            return default

        self.response["id"] = self.club_id
        self.response["url"] = text_or_default(Clubs.Profile.URL)
        self.response["name"] = text_or_default(Clubs.Profile.NAME)
        self.response["officialName"] = text_or_default(Clubs.Profile.NAME_OFFICIAL)
        image_raw = self.get_text_by_xpath(Clubs.Profile.IMAGE)
        image_parts = safe_split(image_raw, "?") or []
        self.response["image"] = image_parts[0] if image_parts else image_raw or ""
        self.response["legalForm"] = self.get_text_by_xpath(Clubs.Profile.LEGAL_FORM)
        self.response["addressLine1"] = text_or_default(Clubs.Profile.ADDRESS_LINE_1)
        self.response["addressLine2"] = self.get_text_by_xpath(Clubs.Profile.ADDRESS_LINE_2)
        self.response["addressLine3"] = self.get_text_by_xpath(Clubs.Profile.ADDRESS_LINE_3)
        self.response["tel"] = self.get_text_by_xpath(Clubs.Profile.TEL)
        self.response["fax"] = self.get_text_by_xpath(Clubs.Profile.FAX)
        self.response["website"] = self.get_text_by_xpath(Clubs.Profile.WEBSITE)
        self.response["foundedOn"] = self.get_text_by_xpath(Clubs.Profile.FOUNDED_ON)
        self.response["members"] = self.get_text_by_xpath(Clubs.Profile.MEMBERS)
        self.response["membersDate"] = safe_regex(
            self.get_text_by_xpath(Clubs.Profile.MEMBERS_DATE),
            REGEX_MEMBERS_DATE,
            "date",
        )
        self.response["otherSports"] = safe_split(self.get_text_by_xpath(Clubs.Profile.OTHER_SPORTS), ",")
        self.response["colors"] = [
            safe_regex(color, REGEX_BG_COLOR, "color")
            for color in self.get_list_by_xpath(Clubs.Profile.COLORS)
            if "#" in color
        ]
        self.response["stadiumName"] = text_or_default(Clubs.Profile.STADIUM_NAME)
        stadium_seats = remove_str(self.get_text_by_xpath(Clubs.Profile.STADIUM_SEATS), ["Seats", "."])
        self.response["stadiumSeats"] = numeric_or_default(stadium_seats)
        transfer_record = self.get_text_by_xpath(Clubs.Profile.TRANSFER_RECORD)
        self.response["currentTransferRecord"] = numeric_or_default(transfer_record)
        self.response["currentMarketValue"] = self.get_text_by_xpath(
            Clubs.Profile.MARKET_VALUE,
            iloc_to=3,
            join_str="",
        )
        self.response["confederation"] = self.get_text_by_xpath(Clubs.Profile.CONFEDERATION)
        self.response["fifaWorldRanking"] = remove_str(self.get_text_by_xpath(Clubs.Profile.RANKING), "Pos")
        self.response["squad"] = {
            "size": numeric_or_default(self.get_text_by_xpath(Clubs.Profile.SQUAD_SIZE)),
            "averageAge": numeric_or_default(self.get_text_by_xpath(Clubs.Profile.SQUAD_AVG_AGE)),
            "foreigners": numeric_or_default(self.get_text_by_xpath(Clubs.Profile.SQUAD_FOREIGNERS)),
            "nationalTeamPlayers": numeric_or_default(self.get_text_by_xpath(Clubs.Profile.SQUAD_NATIONAL_PLAYERS)),
        }
        self.response["league"] = {
            "id": extract_from_url(self.get_text_by_xpath(Clubs.Profile.LEAGUE_ID)),
            "name": self.get_text_by_xpath(Clubs.Profile.LEAGUE_NAME),
            "countryId": safe_regex(self.get_text_by_xpath(Clubs.Profile.LEAGUE_COUNTRY_ID), REGEX_COUNTRY_ID, "id"),
            "countryName": self.get_text_by_xpath(Clubs.Profile.LEAGUE_COUNTRY_NAME),
            "tier": self.get_text_by_xpath(Clubs.Profile.LEAGUE_TIER),
        }
        self.response["historicalCrests"] = [
            (safe_split(crest, "?") or [crest])[0]
            for crest in self.get_list_by_xpath(Clubs.Profile.CRESTS_HISTORICAL)
            if crest
        ]

        return self.response
