"""Official URLs for ingestion (PRD Phase 2)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FundSource:
    display_name: str
    category: str
    amc: str
    slug: str

    @property
    def url(self) -> str:
        return f"https://groww.in/mutual-funds/{self.slug}"


FUND_SOURCES: tuple[FundSource, ...] = (
    FundSource("SBI Nifty Index Fund Direct Growth", "Index / Large Cap", "SBI", "sbi-nifty-index-fund-direct-growth"),
    FundSource("Parag Parikh Flexi Cap Fund Direct Growth", "Flexi Cap", "PPFAS", "parag-parikh-long-term-value-fund-direct-growth"),
    FundSource("HDFC Mid Cap Opportunities Fund Direct Growth", "Mid Cap", "HDFC", "hdfc-mid-cap-opportunities-fund-direct-growth"),
    FundSource("SBI Small Cap Fund Direct Growth", "Small Cap", "SBI", "sbi-small-midcap-fund-direct-growth"),
    FundSource("Mirae Asset ELSS Tax Saver Fund Direct Growth", "ELSS", "Mirae", "mirae-asset-elss-tax-saver-fund-direct-growth"),
    FundSource("Nippon India Large Cap Fund Direct Growth", "Large Cap", "Nippon", "nippon-india-large-cap-fund-direct-growth"),
    FundSource("Kotak Small Cap Fund Direct Growth", "Small Cap", "Kotak", "kotak-midcap-fund-direct-growth"),
    FundSource("HDFC Flexi Cap Fund Direct Growth", "Flexi Cap", "HDFC", "hdfc-equity-fund-direct-growth"),
    FundSource("Motilal Oswal Midcap Fund Direct Growth", "Mid Cap", "Motilal", "motilal-oswal-most-focused-midcap-30-fund-direct-growth"),
    FundSource("UTI Nifty 50 Index Fund Direct Growth", "Index", "UTI", "uti-nifty-fund-direct-growth"),
    FundSource("Axis Midcap Fund Direct Growth", "Mid Cap", "Axis", "axis-midcap-fund-direct-growth"),
    FundSource("ICICI Prudential ELSS Tax Saver Direct Growth", "ELSS", "ICICI", "icici-prudential-long-term-equity-fund-tax-saving-direct-growth"),
    FundSource("SBI Magnum Children's Benefit Fund", "Thematic", "SBI", "sbi-magnum-children-benefit-plan-direct"),
    FundSource("Quant Small Cap Fund Direct Growth", "Small Cap", "Quant", "quant-small-cap-fund-direct-plan-growth"),
    FundSource("Canara Robeco Bluechip Equity Fund Direct Growth", "Large Cap", "Canara Robeco", "canara-robeco-large-cap-fund-direct-growth"),
)


@dataclass(frozen=True)
class SebiSource:
    topic: str
    url: str


SEBI_SOURCES: tuple[SebiSource, ...] = (
    SebiSource("NAV + AUM + AMC", "https://investor.sebi.gov.in/securities-mf-investments.html"),
    SebiSource("Exit load", "https://investor.sebi.gov.in/exit_load.html"),
    SebiSource("Regular vs direct", "https://investor.sebi.gov.in/regular_and_direct_mutual_funds.html"),
    SebiSource("Index funds", "https://investor.sebi.gov.in/index_mutual_fund.html"),
    SebiSource("Understanding MF", "https://investor.sebi.gov.in/understanding_mf.html"),
    SebiSource("Open-ended funds", "https://investor.sebi.gov.in/open_ended_fund.html"),
    SebiSource("Closed-ended funds", "https://investor.sebi.gov.in/closed_ended_fund.html"),
    SebiSource("Interval funds", "https://investor.sebi.gov.in/interval_fund.html"),
    SebiSource("Intro to MF investing (PDF)", "https://investor.sebi.gov.in/pdf/reference-material/ppt/PPT-8-Introduction_to_Mutual_Funds_Investing_Jan24.pdf"),
)


EXTRA_GROWW_PAGES: tuple[str, ...] = (
    "https://groww.in/mutual-funds/equity-funds/large-cap-funds",
    "https://groww.in/mutual-funds/equity-funds/mid-cap-funds",
    "https://groww.in/mutual-funds/equity-funds/small-cap-funds",
    "https://groww.in/mutual-funds/equity-funds/elss-funds",
    "https://groww.in/mutual-funds/index-funds",
    "https://groww.in/mutual-funds/equity-funds/flexi-cap-funds",
)


def all_manifest_urls() -> list[str]:
    urls = [f.url for f in FUND_SOURCES]
    urls.extend(s.url for s in SEBI_SOURCES)
    urls.extend(EXTRA_GROWW_PAGES)
    urls.append("https://play.google.com/store/apps/details?id=com.nextbillion.groww")
    return urls
