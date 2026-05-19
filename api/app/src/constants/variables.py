from src.schemas.parse_pipeline import (
    Amenities,
    AuctionInformation,
    BuildingInformation,
    FinancialStatementExtraction,
    FinancialStatementExtractionHotel,
    HotelInfosSpecific,
    MarketDemographicsReport,
    MetaKeyKPis,
    MetadataFromText,
    PageOfInterest,
    RentRollReport,
    ZoneAttractiveness,
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

# Fixed workbook tabs (order matters for export).
EXCEL_WORKBOOK_SHEETS: tuple[str, ...] = (
    "Summary",
    "Financial statement",
    "Rent roll",
    "Property information",
    "Area attractiveness",
    "Auction",
)

# Pydantic models keyed by LLM extraction step / output bucket.
schemas_dict = {
    "page_of_interest": PageOfInterest,
    "metadata_from_text": MetadataFromText,
    "meta_key_kpis": MetaKeyKPis,
    "rent_roll_report": RentRollReport,
    "financial_statement": FinancialStatementExtraction,
    "financial_statement_hotel": FinancialStatementExtractionHotel,
    "building_report": BuildingInformation,
    "demographics_report": MarketDemographicsReport,
    "attractiveness_report": ZoneAttractiveness,
    "amenities_report": Amenities,
    "hotel_specific_report": HotelInfosSpecific,
    "auction_information": AuctionInformation,
}

# Maps each extraction schema to a ``PageOfInterest`` field (1-based page numbers).
SCHEMA_TO_PAGE_INTEREST_FIELD: dict[str, str] = {
    "metadata_from_text": "metadata_page",
    "meta_key_kpis": "meta_key_kpis_page",
    "building_report": "building_report_page",
    "hotel_specific_report": "hotel_specific_page",
    "rent_roll_report": "rent_roll_page",
    "financial_statement": "financial_summary_page",
    "financial_statement_hotel": "financial_summary_page",
    "demographics_report": "demographics_page",
    "attractiveness_report": "attractiveness_page",
    "amenities_report": "amenities_page",
    "auction_information": "auction_page",
}

# User-facing row labels: section → field key → column A label.
EXCEL_FIELD_LABELS: dict[str, dict[str, str]] = {
    "_common": {
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
        "total_parcel_size_acres": "Parcel size (acres)",
        "number_of_units": "# Units",
    },
    "meta_key_kpis": {
        "kpi_year": "Year",
        "cap_rate": "Cap rate (%)",
        "total_net_operating_income": "NOI ($)",
    },
    "financial_statement": {
        "revenue_year": "Year",
        "gross_potential_rent": "Gross potential rent ($)",
        "vacancy_and_collection_loss": "Vacancy / collection ($)",
        "other_income": "Other income ($)",
        "effective_gross_income": "Effective gross income ($)",
        "taxes": "Property tax ($)",
        "insurance": "Insurance ($)",
        "water_and_sewer": "Water & sewer ($)",
        "electric": "Electric ($)",
        "gas": "Gas ($)",
        "trash": "Trash ($)",
        "utilities_total": "Utilities total ($)",
        "management_fee": "Management fee ($)",
        "repair_and_maintenance": "Repairs & maintenance ($)",
        "general_and_administrative": "G&A ($)",
        "other_operating_expenses": "Other OpEx ($)",
        "total_operating_expenses": "Total OpEx ($)",
        "net_operating_income": "NOI ($)",
    },
    "financial_statement_hotel": {
        "year": "Year",
        "kpis.rooms_count": "Rooms / keys",
        "kpis.occupancy_percentage": "Occupancy (%)",
        "kpis.adr": "ADR ($)",
        "kpis.revpar": "RevPAR ($)",
        "kpis.revpar_change_percentage": "RevPAR change (%)",
        "rooms_revenue": "Rooms revenue ($)",
        "other_operated_departments_revenue": "Other operated revenue ($)",
        "miscellaneous_income": "Misc. income ($)",
        "total_operating_revenue": "Total operating revenue ($)",
        "rooms_expense": "Rooms expense ($)",
        "total_departmental_expenses": "Total departmental expenses ($)",
        "total_departmental_profit": "Total departmental profit ($)",
        "administrative_and_general": "A&G ($)",
        "it_and_telecommunications": "IT & telecom ($)",
        "sales_and_marketing": "Sales & marketing ($)",
        "franchise_fees": "Franchise fees ($)",
        "property_operations_and_maintenance": "POM ($)",
        "utilities": "Utilities ($)",
        "total_undistributed_operating_expenses": "Total undistributed OpEx ($)",
        "gross_operating_profit": "GOP ($)",
        "total_management_fees": "Management fees ($)",
        "income_before_non_operating": "Income before non-operating ($)",
        "property_and_other_taxes": "Property tax ($)",
        "insurance": "Insurance ($)",
        "total_non_operating_income_and_expenses": "Total non-operating ($)",
        "ebitda": "EBITDA ($)",
        "replacement_reserve": "FF&E reserve ($)",
        "net_operating_income": "NOI ($)",
    },
    "rent_roll_report": {
        "unit_name": "Unit / ID",
        "unit_address": "Unit address",
        "unit_size": "Size (SF)",
        "unit_rent_status": "Status",
        "unit_type_of_ownership": "Ownership",
        "unit_rent_price_monthly": "Rent / month ($)",
        "unit_rent_price_yearly": "Rent / year ($)",
        "rent_per_sf": "$/SF / year",
        "unit_rent_start_date": "Lease start",
        "unit_rent_end_date": "Lease end",
        "unit_lease_type": "Lease structure",
        "unit_rent_increases": "Rent increases",
        "renewal_options": "Renewal options",
        "tenant_name": "Tenant",
        "tenant_headquarters": "Tenant HQ",
        "tenant_year_founded": "Year founded",
        "tenant_description": "Tenant summary",
    },
    "building_report": {
        "year_built": "Year built",
        "year_renovated": "Year renovated",
        "construction_type": "Construction",
        "roof_condition": "Roof condition",
        "roof_age": "Roof age (years)",
        "building_height": "Building height (ft)",
        "building_dimensions": "Building dimensions",
        "hvac_system_condition": "HVAC",
        "zoning_urban": "Zoning",
        "flood_zone": "Flood zone",
        "deferred_maintenance": "Deferred maintenance",
        "number_of_floors": "Floors",
        "number_of_rooms": "Rooms",
        "number_of_beds": "Beds",
    },
    "amenities_report": {
        "name": "Amenity",
        "amenity_description": "Description",
        "amenity_size": "Size",
        "amenity_condition": "Condition",
        "number_of_unit_of_the_amenity": "# Units",
    },
    "demographics_report": {
        "area_type": "Area",
        "total_population": "Population",
        "population_growth_percentage": "Pop. growth (%)",
        "number_of_households": "Households",
        "people_per_household": "People / HH",
        "median_age": "Median age",
        "average_age": "Average age",
        "average_household_income": "Avg HH income ($)",
        "median_household_income": "Median HH income ($)",
        "percentage_white": "% White",
        "percentage_black": "% Black",
        "percentage_asian": "% Asian",
        "percentage_other": "% Other",
    },
    "attractiveness_report": {
        "name": "Name",
        "distance": "Distance (mi)",
        "type": "Type",
        "description": "Description",
    },
    "auction_information": {
        "auction_date_start": "Auction start",
        "auction_date_end": "Auction end",
        "auction_location": "Location",
        "auction_type": "Auction type",
        "auction_start_bid": "Starting bid ($)",
        "auction_url": "URL",
        "auction_has_reserved_price": "Reserve (Y/N)",
        "auction_reserve_price": "Reserve price ($)",
    },
}

# Financial statement row styling (revenue block / expense block / totals).
FINANCIAL_REVENUE_ROWS: dict[str, frozenset[str]] = {
    "financial_statement": frozenset({
        "gross_potential_rent",
        "vacancy_and_collection_loss",
        "other_income",
    }),
    "financial_statement_hotel": frozenset({
        "rooms_revenue",
        "other_operated_departments_revenue",
        "miscellaneous_income",
        "kpis.rooms_count",
        "kpis.occupancy_percentage",
        "kpis.adr",
        "kpis.revpar",
        "kpis.revpar_change_percentage",
    }),
}
FINANCIAL_EXPENSE_ROWS: dict[str, frozenset[str]] = {
    "financial_statement": frozenset({
        "taxes",
        "insurance",
        "water_and_sewer",
        "electric",
        "gas",
        "trash",
        "utilities_total",
        "management_fee",
        "repair_and_maintenance",
        "general_and_administrative",
        "other_operating_expenses",
    }),
    "financial_statement_hotel": frozenset({
        "rooms_expense",
        "administrative_and_general",
        "it_and_telecommunications",
        "sales_and_marketing",
        "franchise_fees",
        "property_operations_and_maintenance",
        "utilities",
        "property_and_other_taxes",
        "insurance",
        "replacement_reserve",
        "total_management_fees",
    }),
}
FINANCIAL_TOTAL_ROWS: dict[str, frozenset[str]] = {
    "financial_statement": frozenset({
        "effective_gross_income",
        "total_operating_expenses",
        "net_operating_income",
    }),
    "financial_statement_hotel": frozenset({
        "total_operating_revenue",
        "total_departmental_expenses",
        "total_departmental_profit",
        "total_undistributed_operating_expenses",
        "gross_operating_profit",
        "income_before_non_operating",
        "total_non_operating_income_and_expenses",
        "ebitda",
        "net_operating_income",
    }),
}
# Row order within the financial matrix (keys not listed append at end).
# Keys used only for matrix column headers (omitted from row labels below).
EXCEL_COLUMN_ID_KEYS: dict[str, frozenset[str]] = {
    "meta_key_kpis": frozenset({"kpi_year"}),
    "financial_statement": frozenset({"revenue_year"}),
    "financial_statement_hotel": frozenset({"year"}),
    "rent_roll_report": frozenset(),  # column titles use unit_name + tenant_name composite
}

# Rent roll sheet: titled blocks → field keys (column = unit, row = field).
RENT_ROLL_BLOCKS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Unit description",
        (
            "unit_name",
            "unit_address",
            "unit_size",
            "unit_rent_status",
            "unit_type_of_ownership",
        ),
    ),
    (
        "Unit financials",
        (
            "unit_rent_price_monthly",
            "unit_rent_price_yearly",
            "rent_per_sf",
        ),
    ),
    (
        "Lease & tenant",
        (
            "unit_rent_start_date",
            "unit_rent_end_date",
            "unit_lease_type",
            "unit_rent_increases",
            "renewal_options",
            "tenant_name",
            "tenant_headquarters",
            "tenant_year_founded",
            "tenant_description",
        ),
    ),
)

FINANCIAL_ROW_ORDER: dict[str, tuple[str, ...]] = {
    "financial_statement": (
        "gross_potential_rent",
        "vacancy_and_collection_loss",
        "other_income",
        "effective_gross_income",
        "taxes",
        "insurance",
        "water_and_sewer",
        "electric",
        "gas",
        "trash",
        "utilities_total",
        "management_fee",
        "repair_and_maintenance",
        "general_and_administrative",
        "other_operating_expenses",
        "total_operating_expenses",
        "net_operating_income",
    ),
    "financial_statement_hotel": (
        "year",
        "kpis.rooms_count",
        "kpis.occupancy_percentage",
        "kpis.adr",
        "kpis.revpar",
        "kpis.revpar_change_percentage",
        "rooms_revenue",
        "other_operated_departments_revenue",
        "miscellaneous_income",
        "total_operating_revenue",
        "rooms_expense",
        "total_departmental_expenses",
        "total_departmental_profit",
        "administrative_and_general",
        "it_and_telecommunications",
        "sales_and_marketing",
        "franchise_fees",
        "property_operations_and_maintenance",
        "utilities",
        "total_undistributed_operating_expenses",
        "gross_operating_profit",
        "total_management_fees",
        "income_before_non_operating",
        "property_and_other_taxes",
        "insurance",
        "total_non_operating_income_and_expenses",
        "ebitda",
        "replacement_reserve",
        "net_operating_income",
    ),
}

# Legacy alias (some call sites may still reference sheet titles dict).
EXCEL_SCHEMA_SHEET_TITLES: dict[str, str] = {
    "metadata_from_text": "Summary",
    "financial_statement": "Financial statement",
    "financial_statement_hotel": "Financial statement",
    "rent_roll_report": "Rent roll",
    "building_report": "Property information",
    "demographics_report": "Area attractiveness",
    "attractiveness_report": "Area attractiveness",
    "auction_information": "Auction",
}
