from src.schemas.parse_pipeline import (
    Amenities,
    AuctionInformation,
    BuildingConditions,
    FinancialStatementExtraction,
    FinancialStatementExtractionHotel,
    HotelSpecific,
    MarketDemographicsReport,
    MetadataFromText,
    RentRollReport,
    ZoneAttractiveness,
    PageOfInterest
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

# Fixed workbook tabs (order matters for export). Names align with ``text_llm`` schema keys.
EXCEL_WORKBOOK_SHEETS: tuple[str, ...] = (
    "summary",
    "offer_pictures",
    "rent_roll",
    "financial_statement",
    "building_report",
    "demographics_report",
)

# ``PageOfInterest`` field(s) → Excel tab (1-based PDF page numbers from ``page_extraction``).
EXCEL_SHEET_PAGE_OF_INTEREST_FIELDS: dict[str, str | tuple[str, ...]] = {
    "summary": "metadata_page",
    "offer_pictures": "property_pictures_page",
    "rent_roll": "rent_roll_page",
    "financial_statement": "financial_summary_page",
    "building_report": "building_report_page",
    "demographics_report": ("demographics_page", "attractiveness_page"),
}

# Pydantic models keyed by LLM extraction step / output bucket.
schemas_dict = {
    "page_extraction": PageOfInterest,
    "metadata_from_text": MetadataFromText,
    "rent_roll_report": RentRollReport,
    "financial_statement": FinancialStatementExtraction,
    "financial_statement_hotel": FinancialStatementExtractionHotel,
    "building_report": BuildingConditions,
    "demographics_report": MarketDemographicsReport,
    "attractiveness_report": ZoneAttractiveness,
    "amenities_report": Amenities,
    "hotel_specific_report": HotelSpecific,
    "auction_information": AuctionInformation,
}

# Text-tier LLM: (system_prompt_filename, user_prompt_filename) under ``prompt_templates/``.
# Every key in ``schemas_dict`` must have an entry.
TEXT_SCHEMA_PROMPT_FILES: dict[str, tuple[str, str]] = {
    "page_extraction": (
        "parse_metadata_system_prompt.md",
        "parse_metadata_prompt.md",
    ),
    "metadata_from_text": (
        "parse_metadata_system_prompt.md",
        "parse_metadata_prompt.md",
    ),
    "rent_roll_report": (
        "parse_metadata_system_prompt.md",
        "parse_metadata_prompt.md",
    ),
    "financial_statement": (
        "parse_metadata_system_prompt.md",
        "parse_metadata_prompt.md",
    ),
    "financial_statement_hotel": (
        "parse_metadata_system_prompt.md",
        "parse_metadata_prompt.md",
    ),
    "building_report": (
        "parse_building_report_system_prompt.md",
        "parse_building_report_prompt.md",
    ),
    "demographics_report": (
        "parse_metadata_system_prompt.md",
        "parse_metadata_prompt.md",
    ),
    "attractiveness_report": (
         "parse_metadata_system_prompt.md",
        "parse_metadata_prompt.md",
    ),
    "amenities_report": (
        "parse_metadata_system_prompt.md",
        "parse_metadata_prompt.md",
    ),
    "hotel_specific_report": (
         "parse_metadata_system_prompt.md",
        "parse_metadata_prompt.md",
    ),
    "auction_information": (
        "parse_metadata_system_prompt.md",
        "parse_metadata_prompt.md",
    ),
}

if set(TEXT_SCHEMA_PROMPT_FILES) != set(schemas_dict):
    raise ValueError(
        "TEXT_SCHEMA_PROMPT_FILES and schemas_dict must have the same keys; "
        f"missing={set(schemas_dict) - set(TEXT_SCHEMA_PROMPT_FILES)} "
        f"extra={set(TEXT_SCHEMA_PROMPT_FILES) - set(schemas_dict)}"
    )

# --- PDF text-tier parallel LLM: ``schemas_dict`` key tuples (by asset bucket) ----
# Excludes ``metadata_from_text``, ``auction_information``, vision.
SHARED_AUX_SCHEMAS: tuple[str, ...] = (
    "building_report",
    "demographics_report",
)
STANDARD_AUX_SCHEMAS: tuple[str, ...] = SHARED_AUX_SCHEMAS  + (
    "financial_statement",
    "rent_roll_report"
)

HOTEL_AUX_SCHEMAS: tuple[str, ...] = SHARED_AUX_SCHEMAS + (
    "financial_statement_hotel",
    "hotel_specific_report",
    "amenities_report",
)
LAND_AUX_SCHEMAS: tuple[str, ...] = STANDARD_AUX_SCHEMAS
INDUSTRIAL_AUX_SCHEMAS: tuple[str, ...] = STANDARD_AUX_SCHEMAS
MULTIFAMILY_AUX_SCHEMAS: tuple[str, ...] = STANDARD_AUX_SCHEMAS
RETAIL_AUX_SCHEMAS: tuple[str, ...] = STANDARD_AUX_SCHEMAS

# User-facing row labels: section → field key → column A label.
EXCEL_FIELD_LABELS: dict[str, dict[str, str]] = {
    "_common": {
        "page_number": "Pages (OM)",
    },
    "metadata_from_text": {
        "offer_name": "Offer name",
        "is_portfolio": "Portfolio deal",
        "number_of_properties": "# Properties",
        "city": "City",
        "state": "State",
        "asset_type": "Asset type",
        "transaction_type": "Transaction type",
        "property_name": "Property",
        "asset_sub_type": "Asset subtype",
    },
    "offer_line": {
        "buildings_number": "# Buildings",
        "is_unpriced": "Unpriced",
        "asking_price": "Asking price ($)",
        "occupancy_percentage": "Occupancy (%)",
        "offer_rentable_square_feet": "Rentable SF",
        "offer_parcel_size_acres": "Parcel (acres)",
    },
    "financial_statement": {
        "property_name": "Property",
        "financial_year": "Year / scenario",
        "year_label": "Year / scenario",
        "gross_potential_rent": "Gross potential rent ($)",
        "expense_reimbursements": "Expense reimbursements ($)",
        "other_income": "Other income ($)",
        "gross_scheduled_income": "Gross scheduled income ($)",
        "vacancy_loss": "Vacancy / collection ($)",
        "effective_gross_income": "Effective gross income ($)",
        "taxes_property": "Property tax ($)",
        "insurance": "Insurance ($)",
        "utilities_combined": "Utilities ($)",
        "management_fees": "Management fees ($)",
        "repairs_and_maintenance": "R&M ($)",
        "general_and_administrative": "G&A ($)",
        "other_operating_expenses": "Other OpEx ($)",
        "total_operating_expenses": "Total OpEx ($)",
        "net_operating_income": "NOI ($)",
        "cap_rate": "Cap rate (%)",
    },
    "financial_statement_hotel": {
        "property_name": "Property",
        "financial_year": "Year / scenario",
        "year_label": "Year / scenario",
        "occupancy_percentage": "Occupancy (%)",
        "adr": "ADR ($)",
        "revpar": "RevPAR ($)",
        "revenue_rooms": "Rooms revenue ($)",
        "revenue_food_and_beverage": "F&B revenue ($)",
        "revenue_other_operated_departments": "Other dept revenue ($)",
        "revenue_miscellaneous": "Misc. revenue ($)",
        "total_operating_revenue": "Total operating revenue ($)",
        "expense_rooms": "Rooms expense ($)",
        "expense_food_and_beverage": "F&B expense ($)",
        "expense_other_operated_departments": "Other dept expense ($)",
        "total_departmental_expenses": "Total departmental expenses ($)",
        "total_departmental_profit": "Total departmental profit ($)",
        "administrative_and_general": "A&G ($)",
        "information_and_telecom": "IT & telecom ($)",
        "sales_and_marketing": "Sales & marketing ($)",
        "franchise_fees": "Franchise fees ($)",
        "property_operations_and_maintenance": "POM ($)",
        "utilities_combined": "Utilities ($)",
        "total_undistributed_expenses": "Total undistributed OpEx ($)",
        "gross_operating_profit": "GOP ($)",
        "management_fees_total": "Management fees ($)",
        "income_before_non_operating": "Income before non-operating ($)",
        "taxes_property": "Property tax ($)",
        "insurance_building": "Insurance ($)",
        "other_fixed_charges": "Other fixed ($)",
        "total_non_operating_expenses": "Total non-operating ($)",
        "ebitda": "EBITDA ($)",
        "ffe_replacement_reserve": "FF&E reserve ($)",
        "net_operating_income": "NOI ($)",
    },
    "rent_roll_report": {
        "building_name": "Building",
        "property_name": "Property",
        "unit_id": "Unit / ID",
        "tenant_name": "Tenant",
        "unit_size_sf": "Size (SF)",
        "monthly_rent_usd": "Rent / month ($)",
        "annual_rent_usd": "Rent / year ($)",
        "rent_per_sf_yearly": "$/SF / year",
        "lease_start_date": "Lease start",
        "lease_end_date": "Lease end",
        "lease_structure_type": "Lease structure",
        "lease_remaining_years": "Lease remaining (yrs)",
        "rent_increases": "Rent increases",
        "renewal_options": "Renewal options",
    },
    "building_report": {
        "building_name": "Building name",
        "building_address": "Address",
        "number_tenants_in_building": "Tenants / units",
        "building_ownership_type": "Ownership",
        "apn": "APN",
        "year_built": "Year built",
        "year_renovated": "Year renovated",
        "construction_type": "Construction",
        "roof_condition": "Roof condition",
        "building_height": "Height (ft)",
        "building_surface_sf": "Building SF",
        "floors_count": "Floors",
        "parking_spaces": "Parking spaces",
        "hvac_system_condition": "HVAC",
        "zoning_urban": "Zoning",
        "flood_zone": "Flood zone",
        "deferred_maintenance": "Deferred maintenance",
        "loading_dock_number": "Loading docks",
        "property_name": "Property",
        "property_address": "Address",
    },
    "amenities_report": {
        "name": "Amenity",
        "amenity_description": "Description",
        "amenity_size": "Size (SF)",
    },
    "hotel_specific_report": {
        "brand_affiliation": "Brand",
        "pip_requirement": "PIP requirement",
        "pip_estimated_cost": "PIP est. cost ($)",
        "management_unencumbered": "Mgmt unencumbered",
        "rooms_count": "Rooms",
        "beds_count": "Beds",
    },
    "retail_specific_report": {
        "anchor_tenants": "Anchor tenants",
        "has_drive_thru": "Drive-thru",
        "outparcels_included": "Outparcels included",
        "shadow_anchored": "Shadow anchored",
    },
    "demographics_report": {
        "radius_label": "Catchment",
        "radius_scope": "Catchment",
        "total_population": "Population",
        "population_growth_projection": "Pop. growth (%)",
        "total_households": "Households",
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
        "expense_reimbursements",
        "other_income",
        "gross_scheduled_income",
        "vacancy_loss",
    }),
    "financial_statement_hotel": frozenset({
        "revenue_rooms",
        "revenue_food_and_beverage",
        "revenue_other_operated_departments",
        "revenue_miscellaneous",
        "occupancy_percentage",
        "adr",
        "revpar",
    }),
}
FINANCIAL_EXPENSE_ROWS: dict[str, frozenset[str]] = {
    "financial_statement": frozenset({
        "taxes_property",
        "insurance",
        "utilities_combined",
        "management_fees",
        "repairs_and_maintenance",
        "general_and_administrative",
        "other_operating_expenses",
    }),
    "financial_statement_hotel": frozenset({
        "expense_rooms",
        "expense_food_and_beverage",
        "expense_other_operated_departments",
        "administrative_and_general",
        "information_and_telecom",
        "sales_and_marketing",
        "franchise_fees",
        "property_operations_and_maintenance",
        "utilities_combined",
        "taxes_property",
        "insurance_building",
        "other_fixed_charges",
        "ffe_replacement_reserve",
    }),
}
FINANCIAL_TOTAL_ROWS: dict[str, frozenset[str]] = {
    "financial_statement": frozenset({
        "effective_gross_income",
        "total_operating_expenses",
        "net_operating_income",
        "cap_rate",
    }),
    "financial_statement_hotel": frozenset({
        "total_operating_revenue",
        "total_departmental_expenses",
        "total_departmental_profit",
        "total_undistributed_expenses",
        "gross_operating_profit",
        "management_fees_total",
        "income_before_non_operating",
        "total_non_operating_expenses",
        "ebitda",
        "net_operating_income",
    }),
}
# Row order within the financial matrix (keys not listed append at end).
# Keys used only for matrix column headers (omitted from row labels below).
EXCEL_COLUMN_ID_KEYS: dict[str, frozenset[str]] = {
    "financial_statement": frozenset({"financial_year", "year_label"}),
    "financial_statement_hotel": frozenset({"financial_year", "year_label"}),
    "rent_roll_report": frozenset(),  # column titles use unit_id + tenant_name composite
}

# Rent roll: transposed table column order (unit + rent + lease fields; one Excel row per ``Leases`` entry when a list).
RENT_ROLL_BLOCKS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Unit & tenant",
        (
            "unit_id",
            "tenant_name",
            "unit_size_sf",
        ),
    ),
    (
        "Rent",
        (
            "monthly_rent_usd",
            "annual_rent_usd",
            "rent_per_sf_yearly",
        ),
    ),
    (
        "Lease",
        (
            "lease_start_date",
            "lease_end_date",
            "lease_remaining_years",
            "lease_structure_type",
            "rent_increases",
            "renewal_options",
        ),
    ),
)

FINANCIAL_ROW_ORDER: dict[str, tuple[str, ...]] = {
    "financial_statement": (
        "financial_year",
        "year_label",
        "property_name",
        "gross_potential_rent",
        "expense_reimbursements",
        "other_income",
        "gross_scheduled_income",
        "vacancy_loss",
        "effective_gross_income",
        "taxes_property",
        "insurance",
        "utilities_combined",
        "management_fees",
        "repairs_and_maintenance",
        "general_and_administrative",
        "other_operating_expenses",
        "total_operating_expenses",
        "net_operating_income",
        "cap_rate",
    ),
    "financial_statement_hotel": (
        "financial_year",
        "year_label",
        "property_name",
        "occupancy_percentage",
        "adr",
        "revpar",
        "revenue_rooms",
        "revenue_food_and_beverage",
        "revenue_other_operated_departments",
        "revenue_miscellaneous",
        "total_operating_revenue",
        "expense_rooms",
        "expense_food_and_beverage",
        "expense_other_operated_departments",
        "total_departmental_expenses",
        "total_departmental_profit",
        "administrative_and_general",
        "information_and_telecom",
        "sales_and_marketing",
        "franchise_fees",
        "property_operations_and_maintenance",
        "utilities_combined",
        "total_undistributed_expenses",
        "gross_operating_profit",
        "management_fees_total",
        "income_before_non_operating",
        "taxes_property",
        "insurance_building",
        "other_fixed_charges",
        "total_non_operating_expenses",
        "ebitda",
        "ffe_replacement_reserve",
        "net_operating_income",
    ),
}

# Legacy alias (some call sites may still reference sheet titles dict).
EXCEL_SCHEMA_SHEET_TITLES: dict[str, str] = {
    "page_extraction": "summary",
    "metadata_from_text": "summary",
    "financial_statement": "financial_statement",
    "financial_statement_hotel": "financial_statement",
    "rent_roll_report": "rent_roll",
    "building_report": "building_report",
    "demographics_report": "demographics_report",
    "attractiveness_report": "demographics_report",
    "auction_information": "Auction",
}
