"""Pydantic schemas for LLM / vision extraction (Gemini structured JSON)."""

from typing import List, Optional
from pydantic import BaseModel, Field

class Metainfo(BaseModel):
    page_number: Optional[str] = Field(None, description="Page number where the information comes from in the OM. Can be a list of pages (ex: 1,3,5-7)")

# ==========================================
# 0. ORCHESTRATOR
# ==========================================

class PageOfInterest(BaseModel):
    """Tells from the pdf which page should be put in LLM context for feature extraction """
    metadata_page: List[int] = Field(None, description="List of page numbers where summary / presentation of the property / offer is located.")
    rent_roll_page: List[int] = Field(None, description="List of page numbers where the rent roll is located if it exists.")
    financial_summary_page: List[int] = Field(None, description="List of page numbers where the financial summary is located, including expenses, revenues. All the key financials in detail. Give all the pages if multi year.")
    demographics_page: Optional[List[int]] = Field(None, description="List of page numbers where the demographics is located. Usually 1, 3, 5 miles statistics.")
    attractiveness_page: Optional[List[int]] = Field(None, description="List of page numbers where the close points of interest are described to tell how good is the property.")
    auction_page: Optional[List[int]] = Field(None, description="List of page numbers where the auction details is located, if this is an auction.")
    amenities_page: Optional[List[int]] = Field(None, description="List of page numbers where the property amenities are described (parking lot, space to be built, pool, spa, etc.).")
    building_report_page: Optional[List[int]] = Field(None, description="List of page numbers where the building detail is located, when built, condition, renovated, description, etc.")
    hotel_specific_page: Optional[List[int]] = Field(None, description="List of page numbers where the hotel specific details are located, such as amenities, rooms, etc. (ex: number of rooms if hotel).")
    meta_key_kpis_page: Optional[List[int]] = Field(None, description="List of page numbers where the key financials are located, such as cap rate, total net operating income, for this year or in pro format.")

# ==========================================
# 1. METADATA (FAST TIER)
# ==========================================
class MetadataFromText(Metainfo):
    """Structured CRE-ish metadata from raw PDF text (fast tier — text-only LLM)."""
    
    property_name: Optional[str] = Field(None, description="Name of the property")
    property_address: Optional[str] = Field(None, description="Address of the property: street, city, state, zip")
    city: Optional[str] = Field(None, description="Extracted city for quick filtering")
    state: Optional[str] = Field(None, description="Extracted 2-letter state code (ex: TX, NY)")
    asset_type: Optional[str] = Field(None, description="Type of asset: office, retail, industrial, multifamily, hotel, vacant land.")
    asking_price: Optional[float] = Field(None, description="Asking price in USD, or 'Market/Inquire' / 'Unpriced'")
    lot_lease_type: Optional[str] = Field(None, description="Lot lease type: NNN, NN, Modified Gross, Gross, FSG")
    type_of_sale: Optional[str] = Field(None, description="Type of sale: auction or private sale.")

    total_rentable_square_feet: Optional[float] = Field(None, description="Total rentable square feet (NRA/GBA)")
    total_available_square_feet_for_rent: Optional[float] = Field(None, description="Total available square feet (NRA/GBA) for rent")
    total_parcel_size_acres: Optional[float] = Field(None, description="Total parcel size including building and land / parking in acres. If in square feet, convert to acres.")
    
    number_of_units: Optional[int] = Field(None, description="Number of tenants, units, or apartments. Same than rent roll size.")

class MetaKeyKPiPerYear(BaseModel):
    """Key performance indicators for the OM."""
    kpi_year: Optional[str] = Field(None, description="Year of the KPI.")
    cap_rate: Optional[float] = Field(None, description="Cap rate as a percentage (ex: 6.25%)")
    total_net_operating_income: Optional[float] = Field(None, description="Total net operating income in USD.")

class MetaKeyKPis(Metainfo):
    """
    cap_rate and total_net_operating_income per year for the OM.
    """
    cap_noi_per_year: List[MetaKeyKPiPerYear] = Field(
        default_factory=list,
        description="List of yearly financial key information extracted from the document.",
    )

# ==========================================
# 2. RENT ROLL (DEEP VISION / TABLE TIER)
# ==========================================

class RentRollRow(BaseModel):
    """Each line Represents a single item/tenant in a CRE Rent Roll or OM document."""
    
    unit_name: Optional[str] = Field(None, description="Name of the unit or ID of the unit. Ex: 101, 102, etc.")
    unit_address: Optional[str] = Field(None, description="Address of the unit")
    unit_size: Optional[int] = Field(None, description="Unit size in square feet (SF)")
    unit_rent_price_monthly: Optional[float] = Field(None, description="Current year Monthly rent price in USD.")
    unit_rent_price_yearly: Optional[float] = Field(None, description="Current year Yearly rent price in USD.")
    rent_per_sf: Optional[float] = Field(None, description="Current year Yearly Rent per square foot ($/SF/Yr). Common in Retail/Office.")
    
    unit_type_of_ownership: Optional[str] = Field(None, description="Type of ownership: Fee Simple, Leasehold, Joint Venture, etc.")
    unit_rent_status: Optional[str] = Field(None, description="Status: Vacant, Occupied, Leased but not occupied")
    unit_rent_start_date: Optional[str] = Field(None, description="Lease commencement date")
    unit_rent_end_date: Optional[str] = Field(None, description="Lease expiration date")
    unit_lease_type: Optional[str] = Field(None, description="Lease structure: NNN, NN, Modified Gross, Gross, FSG")
    
    tenant_name: Optional[str] = Field(None, description="Tenant corporate name (ex: Starbucks, Vacant, Corporate Lease). If the name exists.")
    tenant_headquarters: Optional[str] = Field(None, description="Tenant headquarters address or city name")
    tenant_year_founded: Optional[int] = Field(None, description="Year the tenant was founded.")
    tenant_description: Optional[str] = Field(None, description="Brief 1 to 2 sentences summary of what the tenant is doing")

    unit_rent_increases: Optional[str] = Field(None, description="Details about rent increases (ex: 3% annually, $0.50/SF in 2027, CPI linked)")
    renewal_options: Optional[str] = Field(None, description="Tenant options to renew (ex: Two 5-year options at market rate)")

class RentRollReport(Metainfo):
    """Full rent roll table extracted from OM pages."""
    rows: List[RentRollRow] = Field(
        default_factory=list,
        description="One row per tenant or unit in the rent roll.",
    )

# ==========================================
# 3. FINANCIAL STATEMENTS (COMBINED & DUAL-COLUMN)
# ==========================================
class StandardKPI(BaseModel):
    """
    Complete Financial Operating & Income Statement.
    Captures both revenues and expenses side-by-side (In-Place vs Pro-Forma).
    """

    revenue_year: Optional[str] = Field(None, description="Year of the revenue recorded. Record as proformat if so.")

    # --- REVENUES (Income) ---
    gross_potential_rent: Optional[float] = Field(None, description="Gross potential rent (GPR)")
    vacancy_and_collection_loss: Optional[float] = Field(None, description="Vacancy loss, often a % or absolute negative USD")
    other_income: Optional[float] = Field(None, description="Total other income (parking, laundry, storage, etc.)")
    effective_gross_income: Optional[float] = Field(None, description="Effective Gross Income (EGI)")

    # --- EXPENSES (OpEx) ---
    taxes: Optional[float] = Field(None, description="Real Estate / Property Taxes")
    insurance: Optional[float] = Field(None, description="Property Insurance")
    
    # Regrouper les utilities évite que le LLM invente des ventilations arbitraires
    water_and_sewer: Optional[float] = Field(None, description="Water and Sewer cost")
    electric: Optional[float] = Field(None, description="Electric cost")
    gas: Optional[float] = Field(None, description="Gas cost")
    trash: Optional[float] = Field(None, description="Trash / garbage management cost")
    utilities_total: Optional[float] = Field(None, description="Total Utilities (Water, Electric, Gas, Trash) combined")
    
    management_fee: Optional[float] = Field(None, description="Property Management fees")
    repair_and_maintenance: Optional[float] = Field(None, description="Repairs, maintenance, and turnover costs")
    general_and_administrative: Optional[float] = Field(None, description="Admin, legal, marketing, and payroll expenses")
    other_operating_expenses: Optional[float] = Field(None, description="Other operating expenses besides the ones listed above")
    total_operating_expenses: Optional[float] = Field(None, description="Total Operating Expenses (OpEx)")
    
    # --- BOTTOM LINE --- NOI = EGI - Operating Expenses
    net_operating_income: Optional[float] = Field(None, description="Net Operating Income (NOI)")

class FinancialStatementExtraction(Metainfo):
    """
    Complete Financial Operating & Income Statement.
    Captures both revenues and expenses side-by-side (In-Place vs Pro-Forma).
    """
    historical_and_proforma_years: List[StandardKPI] = Field(
        default_factory=list,
        description="List of yearly financial data sheets extracted horizontally from the document.",
    )

class HotelKPIs(BaseModel):
    """Core hospitality performance indicators for a given year."""
    rooms_count: Optional[int] = Field(None, description="Total number of rooms keys available (75 in this case)")
    occupancy_percentage: Optional[float] = Field(None, description="Occupancy rate as a percentage (e.g., 71.0 for 71%)")
    adr: Optional[float] = Field(None, description="Average Daily Rate in USD ($)")
    revpar: Optional[float] = Field(None, description="Revenue Per Available Room in USD ($)")
    revpar_change_percentage: Optional[float] = Field(None, description="Year-over-year RevPAR growth percentage")

class HotelYearlyData(BaseModel):
    """Bundles KPIs and line item dollar amounts ($) for a specific fiscal or calendar year."""

    year: Optional[str] = Field(None, description="The year label, e.g., '2021', '2022', or '2023'")
    kpis: Optional[HotelKPIs] = Field(None, description="Top-line operational performance metrics")
    
    # --- OPERATING REVENUE ($) ---
    rooms_revenue: Optional[float] = Field(None, description="Revenue generated from room rentals")
    other_operated_departments_revenue: Optional[float] = Field(None, description="Food & Beverage, minor departments, etc.")
    miscellaneous_income: Optional[float] = Field(None, description="Other minor operating income streams")
    total_operating_revenue: Optional[float] = Field(None, description="Total Gross Operating Revenue")

    # --- DEPARTMENTAL EXPENSES ($) ---
    rooms_expense: Optional[float] = Field(None, description="Direct expenses related to rooms (housekeeping, laundry, etc.)")
    total_departmental_expenses: Optional[float] = Field(None, description="Sum of all direct departmental expenses")
    total_departmental_profit: Optional[float] = Field(None, description="Total Departmental Profit")

    # --- UNDISTRIBUTED OPERATING EXPENSES ($) ---
    administrative_and_general: Optional[float] = Field(None, description="A&G expenses, payroll, legal")
    it_and_telecommunications: Optional[float] = Field(None, description="Information and telecom systems")
    sales_and_marketing: Optional[float] = Field(None, description="Marketing, advertising, and franchise sales efforts")
    franchise_fees: Optional[float] = Field(None, description="Franchise / Royalty fees paid to the brand")
    property_operations_and_maintenance: Optional[float] = Field(None, description="POM expenses, engineering, repairs")
    utilities: Optional[float] = Field(None, description="Electricity, water, gas, waste management")
    total_undistributed_operating_expenses: Optional[float] = Field(None, description="Total Undistributed Operating Expenses")

    # --- PROFITS & FEES ($) ---
    gross_operating_profit: Optional[float] = Field(None, description="Gross Operating Profit (GOP)")
    total_management_fees: Optional[float] = Field(None, description="Base and incentive management fees")
    income_before_non_operating: Optional[float] = Field(None, description="Income Before Non-Operating Income & Expenses")

    # --- NON-OPERATING INCOME & EXPENSES ($) ---
    property_and_other_taxes: Optional[float] = Field(None, description="Real Estate and Property Taxes")
    insurance: Optional[float] = Field(None, description="Property and liability insurance")
    total_non_operating_income_and_expenses: Optional[float] = Field(None, description="Sum of fixed/non-operating costs")

    # --- BOTTOM LINES ($) ---
    ebitda: Optional[float] = Field(None, description="EBITDA / Adjusted GOP")
    replacement_reserve: Optional[float] = Field(None, description="FF&E Reserve (Furniture, Fixtures, and Equipment)")
    net_operating_income: Optional[float] = Field(None, description="Net Operating Income (NOI)")


class FinancialStatementExtractionHotel(Metainfo):
    """
    Complete Financial Operating & Income Statement for Hospitality/Hotel Assets.
    Captures multi-year arrays focusing purely on absolute dollar amounts ($).
    """

    historical_and_proforma_years: List[HotelYearlyData] = Field(
        default_factory=list,
        description="List of yearly financial data sheets extracted horizontally from the document.",
    )

# ==========================================
# 4. PROPERTY CONDITION REPORT
# ==========================================
class HotelInfosSpecific(Metainfo):
    """Technical and physical structural constraints from the OM text."""

    number_of_floors: Optional[int] = Field(None, description="Number of floors of the property, also called stories.")
    number_of_rooms: Optional[int] = Field(None, description="Number of rooms of the property.")
    number_of_beds: Optional[int] = Field(None, description="Number of beds of the property.")

class Amenity(BaseModel):
    """Amenity description of the property, besides the hotel rooms amenities."""
    name: Optional[str] = Field(None, description="Name of the amenity: pool, gym, spa, meeting rooms, event space, parking.")
    amenity_description: Optional[str] = Field(None, description="Description of the amenity.")
    amenity_size: Optional[str] = Field(None, description="Size in square feet of the amenity.")
    amenity_condition: Optional[str] = Field(None, description="Condition of the amenity: good, bad, needs repair, etc. If not stated, set to 'good'.")
    number_of_unit_of_the_amenity: Optional[int] = Field(None, description="Number of units of this amenity.")

class Amenities(Metainfo):
    """Amenities of the property."""
    amenities: Optional[List[Amenity]] = Field(None, description="List of amenities of the property (ex: pool, gym, spa, meeting rooms, parking, etc.)")

class BuildingInformation(BaseModel):
    """Technical and physical structural constraints from the OM text."""

    year_built: Optional[int] = Field(None, description="Year built original")
    year_renovated: Optional[int] = Field(None, description="Year of last major renovation, 'None' if blank")
    construction_type: Optional[str] = Field(None, description="Construction type: wood frame, masonry, steel, concrete tilt-up")
    roof_condition: Optional[str] = Field(None, description="Roof condition notes or rating")
    roof_age: Optional[int] = Field(None, description="Roof age in years or date of last replacement")
    building_height: Optional[int] = Field(None, description="Building height in feet.")
    building_dimensions: Optional[str] = Field(None, description="Building dimensions in square feet.")
    parking_spaces: Optional[int] = Field(None, description="Number of parking spaces.")

    hvac_system_condition: Optional[str] = Field(None, description="HVAC details: Age, central vs individual units, tenant vs landlord responsibility")
    zoning_urban: Optional[str] = Field(None, description="Official zoning code (ex: C-3, M-1, GR) and overlay if any")
    flood_zone: Optional[str] = Field(None, description="Flood zone of the property: A, B, C, X, etc.")
    deferred_maintenance: Optional[str] = Field(None, description="Any explicit mention of immediate repairs needed (Deferred Maintenance)")

# ==========================================
# 5. Demographics / attractiveness Report
# ==========================================

class PointOfInterest(BaseModel):
    """A point of interest."""
    name: Optional[str] = Field(None, description="Name of the point of interest.")
    distance: Optional[float] = Field(None, description="Distance from the property in miles.")
    type: Optional[str] = Field(None, description="Type of the point of interest: restaurant, hotel, shopping center, etc.")
    description: Optional[str] = Field(None, description="Description of the point interest and why this is interesting..")

class ZoneAttractiveness(Metainfo):
    """Close points of interest ."""
    zone_attractiveness: Optional[List[PointOfInterest]] = Field(None, description="List of points of interest close to the property.")

class DemographicColumn(BaseModel):
    """Represents a specific demographic catchment area (e.g., 1-Mile Radius, 10-Min Drive Time)."""
    
    area_type: Optional[str] = Field(None, description="The scope of the column. Examples: '1-Mile Radius', '3-Mile Radius', '5-Mile Radius', '10-Min Drive Time'.")
    total_population: Optional[int] = Field(None, description="Total population within this area.")
    population_growth_percentage: Optional[float] = Field(None, description="Historical or projected population growth rate (ex: +1.2% annually or 5-year projection).")
    number_of_households: Optional[int] = Field(None, description="Total number of households (foyers) in the area.")
    people_per_household: Optional[float] = Field(None, description="Average number of people per household in the area.")
    median_age: Optional[float] = Field(None, description="The median age of the population in this area.")
    average_age: Optional[float] = Field(None, description="The average age of the population in this area.")

    average_household_income: Optional[float] = Field(None, description="Average Household Income in USD (often abbreviated as AHHI).")
    median_household_income: Optional[float] = Field(None, description="Median Household Income in USD.")
    
    percentage_white: Optional[float] = Field(None, description="Percentage of white population in the area.")
    percentage_black: Optional[float] = Field(None, description="Percentage of black population in the area.")
    percentage_asian: Optional[float] = Field(None, description="Percentage of asian population in the area.")
    percentage_other: Optional[float] = Field(None, description="Percentage of other population in the area.")

class MarketDemographicsReport(Metainfo):
    """
    Table extracted from the market analysis or demographics page of the OM.
    Captures multi-radius or multi-drive-time data dynamically.
    """
    
    # Liste dynamique des colonnes de rayons (1, 3, 5 miles ou autres)
    catchment_areas: Optional[List[DemographicColumn]] = Field(default=[], description="List of demographic metrics broken down by radius or drive time columns found in the OM.")

# ==========================================
# 6. Auction Information
# ==========================================
class AuctionInformation(Metainfo):
    """Information about the auction."""

    auction_date_start: Optional[str] = Field(None, description="Date of the auction start.")
    auction_date_end: Optional[str] = Field(None, description="Date of the auction end.")
    auction_location: Optional[str] = Field(None, description="Location of the auction.")
    auction_type: Optional[str] = Field(None, description="Type of auction: online, in-person, etc.")
    auction_start_bid: Optional[float] = Field(None, description="Start bid of the auction in USD.")
    
    auction_url: Optional[str] = Field(None, description="URL of the auction.")
    auction_has_reserved_price: Optional[bool] = Field(None, description="Whether the auction has a reserved price.")
    auction_reserve_price: Optional[float] = Field(None, description="Reserve price of the auction in USD.")


#### vision table extraction

class VisionTableExtraction(BaseModel):
    """
    Table extracted from a page image (rent roll, financial summary, etc.).
    Strict shape for ``response_mime_type=application/json`` validation.
    """

    page_kind: str = Field(
        description="rent_roll | financial_summary | other",
    )
    title: str = ""
    columns: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    confidence: str = Field(default="medium")
    raw_notes: str = ""
