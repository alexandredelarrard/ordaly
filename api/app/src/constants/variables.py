from src.schemas.parse_pipeline import (
    MetadataFromText,
    RentRollTableExtraction,
    FinancialStatementExtraction,
    PropertyConditionReport,
    MarketDemographicsReport,
    AuctionInformation
)

# for crawling & cleaning steps : naming
class Naming:
    def __init__(self):

        # crawling
        self.id_item = "id_item"
        self.id_auction = "id_auction"
        self.id_picture = "id_picture"
        self.id_picture_display = "id_picture_display"

# date format
DATE_FORMAT = "%Y-%m-%d"
DATE_HOUR_FORMAT = "%Y-%m-%d %H:%M:%S"

# User-facing Excel worksheet titles (internal schema key → tab name).
EXCEL_SCHEMA_SHEET_TITLES: dict[str, str] = {
    "metadata_from_text": "Summary",
    "rent_roll_table_extraction": "Rent roll",
    "financial_statement": "Financial statement",
    "property_condition_report": "Property condition",
    "demographics_report": "Demographics",
    "auction_information": "Auction information",
}

# scehmas for output parser
schemas_dict = {
    "metadata_from_text": MetadataFromText,
    "rent_roll_table_extraction": RentRollTableExtraction,
    "financial_statement": FinancialStatementExtraction,
    "property_condition_report": PropertyConditionReport,
    "demographics_report": MarketDemographicsReport,
    "auction_information": AuctionInformation,
}

# Shorter, user-facing Excel row/column titles (path = dotted key or parent.child).
# Used by ``text_llm_excel``; unknown paths fall back to Pydantic descriptions.
EXCEL_FIELD_LABELS: dict[str, dict[str, str]] = {
    "_metainfo": {
        "page_number": "Pages (OM)",
    },
    "metadata_from_text": {
        "property_name": "Property",
        "property_address": "Address",
        "city": "City",
        "state": "State",
        "asset_type": "Asset type",
        "asking_price": "Asking price ($)",
        "lot_lease_type": "Lease type",
        "type_of_sale": "Sale type",
        "total_rentable_square_feet": "Rentable SF",
        "total_available_square_feet_for_rent": "Available SF",
        "total_parcel_size": "Parcel size SF",
        "number_of_units": "# Units",
        "number_of_buildings": "# Buildings",
        "cap_rate.in_place_t12": "Cap rate — T-12 (%)",
        "cap_rate.pro_forma_year1": "Cap rate — Y1 (%)",
        "total_net_operating_income.in_place_t12": "NOI — T-12 ($)",
        "total_net_operating_income.pro_forma_year1": "NOI — Y1 ($)",
        "summary_col_t12": "T-12",
        "summary_col_y1": "Y1",
        "summary_cap_rate": "Cap (%)",
        "summary_noi": "NOI ($)",
    },
    "rent_roll_table_extraction": {
        "rows": "Tenants",
        "tenant_name": "Tenant",
        "tenant_headquarters": "Tenant HQ",
        "tenant_year_founded": "Year founded",
        "tenant_description": "Tenant summary",
        "unit_size": "Size (SF)",
        "rent_per_sf.in_place_t12": "$/SF-Yr — T-12",
        "rent_per_sf.pro_forma_year1": "$/SF-Yr — Y1",
        "unit_rent_price_monthly.in_place_t12": "Rent / mo — T-12 ($)",
        "unit_rent_price_monthly.pro_forma_year1": "Rent / mo — Y1 ($)",
        "unit_rent_price_yearly.in_place_t12": "Rent / yr — T-12 ($)",
        "unit_rent_price_yearly.pro_forma_year1": "Rent / yr — Y1 ($)",
        "unit_type_of_ownership": "Ownership",
        "unit_rent_status": "Status",
        "unit_rent_start_date": "Lease start",
        "unit_rent_end_date": "Lease end",
        "unit_lease_type": "Lease str.",
        "unit_rent_increases": "Rent increases",
        "renewal_options": "Renewals",
        "table_yearly_rent": "Yearly rent ($)",
        "table_monthly_rent": "Monthly rent ($)",
        "rent_pivot_t12": "T-12",
        "rent_pivot_y1": "Y1",
    },
    "financial_statement": {
        "gross_potential_rent.in_place_t12": "GPR — T-12 ($)",
        "gross_potential_rent.pro_forma_year1": "GPR — Y1 ($)",
        "vacancy_and_collection_loss.in_place_t12": "Vacancy / coll. — T-12",
        "vacancy_and_collection_loss.pro_forma_year1": "Vacancy / coll. — Y1",
        "other_income.in_place_t12": "Other income — T-12",
        "other_income.pro_forma_year1": "Other income — Y1",
        "effective_gross_income.in_place_t12": "EGI — T-12",
        "effective_gross_income.pro_forma_year1": "EGI — Y1",
        "taxes.in_place_t12": "Taxes — T-12",
        "taxes.pro_forma_year1": "Taxes — Y1",
        "insurance.in_place_t12": "Insurance — T-12",
        "insurance.pro_forma_year1": "Insurance — Y1",
        "utilities_total.in_place_t12": "Utilities — T-12",
        "utilities_total.pro_forma_year1": "Utilities — Y1",
        "management_fee.in_place_t12": "Mgmt fee — T-12",
        "management_fee.pro_forma_year1": "Mgmt fee — Y1",
        "repair_and_maintenance.in_place_t12": "R&M — T-12",
        "repair_and_maintenance.pro_forma_year1": "R&M — Y1",
        "general_and_administrative.in_place_t12": "G&A — T-12",
        "general_and_administrative.pro_forma_year1": "G&A — Y1",
        "total_operating_expenses.in_place_t12": "Total OpEx — T-12",
        "total_operating_expenses.pro_forma_year1": "Total OpEx — Y1",
        "net_operating_income.in_place_t12": "NOI — T-12",
        "net_operating_income.pro_forma_year1": "NOI — Y1",
        "gross_potential_rent": "GPR",
        "vacancy_and_collection_loss": "Vacancy / collection",
        "other_income": "Other income",
        "effective_gross_income": "EGI",
        "taxes": "Property tax",
        "insurance": "Insurance",
        "utilities_total": "Utilities",
        "management_fee": "Management fee",
        "repair_and_maintenance": "Repairs & maint.",
        "general_and_administrative": "G&A",
        "total_operating_expenses": "Total OpEx",
        "net_operating_income": "NOI",
    },
    "property_condition_report": {
        "year_built": "Year built",
        "year_renovated": "Year renovated",
        "construction_type": "Construction",
        "roof_condition": "Roof",
        "roof_age": "Roof age",
        "hvac_system_condition": "HVAC",
        "parking_spaces": "Parking stalls",
        "zoning_urban": "Zoning",
        "deferred_maintenance": "Deferred maint.",
    },
    "demographics_report": {
        "submarket_vacancy_rate": "Submarket vacancy (%)",
        "submarket_market_rent": "Submarket rent ($)",
        "area_type": "Area",
        "total_population": "Population",
        "population_growth_percentage": "Pop. growth (%)",
        "number_of_households": "Households",
        "people_per_household": "People / HH",
        "median_age": "Median age",
        "average_age": "Average age",
        "average_household_income": "Avg HH income ($)",
        "median_household_income": "Median HH inc. ($)",
        "percentage_white": "% White",
        "percentage_black": "% Black",
        "percentage_asian": "% Asian",
        "percentage_other": "% Other",
        "percentage_male": "% Male",
        "percentage_female": "% Female",
        "vehicles_per_day": "Vehicles / day",
    },
    "auction_information": {
        "auction_date_start": "Auction start",
        "auction_date_end": "Auction end",
        "auction_location": "Location",
        "auction_type": "Auction type",
        "auction_url": "URL",
        "auction_has_reserved_price": "Reserve (Y/N)",
        "auction_reserved_price": "Reserve price ($)",
    },
}