"""Pydantic schemas for LLM / vision extraction (Gemini structured JSON)."""

from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime 

NOW = datetime.today().strftime("YYYY-MM-DD")

class Confidence(BaseModel):
    """gives confidence score regarding the pydantic schema filled to tell user need to double check or not."""
    confidence_answer: int = Field(5, description="A score between 0 and 10, 10 being full confidence in all the answers, 0 being no confidence at all.")

# ==========================================
# 0. ORCHESTRATOR
# ==========================================

class PageOfInterest(BaseModel):
    """Key pages in the pdf where to find the relevant information."""
    metadata_page: List[int] = Field([], description="List of 1 to 3 key pages where the executive summary, offer summary is located. Should have a table of key descriptions of the offer.")
    rent_roll_page: Optional[List[int]] = Field(None, description="List of few key pages where the rent roll numbers are displayed in a table. Give pages where the rent roll tables are.")
    financial_summary_page: Optional[List[int]] = Field(None, description="List of key pages where the financial details are located: revenue, expenses, net operating income, cap rate. Give pages where the financial tables are.")
    demographics_page: Optional[List[int]] = Field(None, description="List of key pages where demographic statistics are in a table.")
    auction_page: Optional[List[int]] = Field(None, description="List of page numbers where the auction details is located, if this is an auction.")
    amenities_page: Optional[List[int]] = Field(None, description="List of page numbers where the property amenities are described (parking lot, space to be built, pool, spa, etc.).")
    building_report_page: Optional[List[int]] = Field(None, description="List of key pages where the building description / condition are located. Give the ones with tables and key information details.")
    hotel_specific_page: Optional[List[int]] = Field(None, description="List of page numbers where the hotel specific details are located, such as amenities, rooms, etc. (ex: number of rooms if hotel), if this is a hotel.")
    
# ==========================================
# 1. METADATA (FAST TIER)
# ==========================================

class Offer(BaseModel):
    """Details regarding each priced offer in the OM. An offer can have several buildings"""

    # investment details 
    asset_name: Optional[str] = Field(None, description="Name of the offer or the asset to be bought. If cannot find any, put the asset address.")
    buildings_number: Optional[int] = Field(None, description="Number of buildings for the offer. One building can have several units.")
    is_unpriced: bool = Field(False, description="True if the OM says 'Market' or 'Inquire for Pricing'")
    asking_price: Optional[float] = Field(None, description="Give the building asked price in USD. Usually in Summary pages. None if Auction or no proposed price.")
    occupancy_percentage: Optional[float] = Field(None, description="Building occupancy rate. If building has several units, this is the average building occupancy rate.")
    offer_rentable_square_feet: Optional[float] = Field(None, description="Building rentable square feet for the offer. Also called GLA")
    offer_parcel_size_acres: Optional[float] = Field(None, description="Offer parcel size including building and land / parking in acres. If in square feet, convert to acres.")

class MetadataFromText(Confidence):
    """Structured CRE-ish metadata from raw PDF text."""
    
    offer_name: Optional[str] = Field(None, description="Name of the overall offer, pdf header or offer name given in the summary.")
    is_portfolio: Optional[bool] = Field(False, description="True if the deal contains multiple separate offers.")
    number_of_properties: int = Field(1, description="Total count of priced properties in this offer.")
    city: Optional[str] = Field(None, description="City of the offer")
    state: Optional[str] = Field(None, description="Extracted 2-letter state code (ex: TX, NY)")
    asset_type: Optional[str] = Field(None, description="One of the following asset type: Office, Retail, Industrial, Multifamily, Hospitality, Land.")
    transaction_type: str = Field(..., description="One of the 2 types of offer: Private Sale or Auction")
    
    asset: Optional[List[Offer]] = Field(..., description="List each offer detail in the OM.")


class Building(BaseModel):
    """Technical and physical structural constraints for each single building of the OM."""

    building_name : Optional[str] = Field(None, description="Name of the building, either the main tenant or the building address if no denomination.")
    building_address: Optional[str] = Field(None, description="Address of the building: street, city, state, zip.")
    number_tenants_in_building:  Optional[int] = Field(1, description="Total possible number of tenants in the building, including vacants. Give number of units if multi units. For hotel give None. A vacancy counts for 1.")
    building_ownership_type:  Optional[str] = Field(None, description="Ownership type. Can be one amongst: Fee simple, Leased Fee, Leasehold or Retail Condo.")
    apn:  Optional[str] = Field(None, description="APN reference of the building.")

    year_built: Optional[int] = Field(None, description="Building year built.")
    year_renovated: Optional[int] = Field(None, description="Building Year of last major renovation.")
    construction_type: Optional[str] = Field(None, description="Main construction type: wood, masonry, steel, concrete, etc.")
    roof_condition: Optional[str] = Field(None, description="Building roof condition notes or rating. Brief roof condition description if no rating.")
    
    building_height: Optional[int] = Field(None, description="Building height in feet.")
    building_surface_sf: Optional[int] = Field(None, description="Building surface in square feet.")
    floors_count: Optional[int] = Field(1, description="Number of floors or stories. Minimum is 1, even if not specified.")
    parking_spaces: Optional[int] = Field(None, description="Number of parking spaces.")

    hvac_system_condition: Optional[str] = Field(None, description="HVAC details: Age, central vs individual units. Also tell if this is tenant vs landlord responsibility")
    zoning_urban: Optional[str] = Field(None, description="Official zoning code (ex: C-3, M-1, GR). Or type of zoning if no code. e.g: 'Retail zone' ")
    flood_zone: Optional[str] = Field(None, description="Flood zone of the property: A, B, C, X, etc.")
    deferred_maintenance: Optional[str] = Field(None, description="Any explicit mention of immediate repairs needed (Deferred Maintenance)")

    loading_dock_number: Optional[int] = Field(0, description="Number of loading docks, important for industrial building.")

class BuildingConditions(Confidence):
    """Details regarding each building. An offer can have several buildings"""

    assets: Optional[List[Building]] = Field(None, description="List of each building detailed in the OM.")

############# sepcific metadata for each asset type #############
class HotelSpecific(BaseModel):
    brand_affiliation: Optional[str] = Field(None, description="Brand of the hotel, leasing the building,")
    pip_requirement: Optional[str] = Field(None, description="Details on Property Improvement Plan requirements")
    pip_estimated_cost: Optional[float] = Field(None, description="Estimated cost for mandatory PIP updates")
    management_unencumbered: Optional[bool] = Field(None, description="True if the buyer can bring their own management")
    
    rooms_count: Optional[int] = Field(None, description="Number of rooms of the property.")
    beds_count: Optional[int] = Field(None, description="Number of beds of the property.")

# ==========================================
# 2. RENT ROLL (DEEP VISION / TABLE TIER)
# ==========================================

class RentRollRow(BaseModel): 
    """Represents a clean row item extracted out of multi-tenant leasing tables."""
    
    unit_id: Optional[str] = Field(None, description="Unit, tenant or physical suite designation (e.g., 'Suite 104-A'). Give the type of tenant if no unit ID. e.g: 'Residential Tenant', 'Single Tenant'")
    unit_size_sf: Optional[int] = Field(None, description="Total space footprint area measured in square feet for the unit.")
    tenant_name: Optional[str] = Field(..., description="Tenant name, especially for retail. Use 'Vacant' if space is unleased.")
    
    # Financial Runs
    monthly_rent_usd: Optional[float] = Field(None, description="Unit monthly rent.")
    annual_rent_usd: Optional[float] = Field(None, description="Unit yearly rent, must match 12*monthly rent.")
    rent_per_sf_yearly: Optional[float] = Field(None, description="Yearly unit rent divided by unit square footage ($/SF/Yr).")
    
    # Lease Lifespan Mechanics
    lease_start_date: Optional[str] = Field(None, description="Lease commencement or move-in date. Format the date to YYYY-MM-DD. If Month to Month rent, put MTM.")
    lease_end_date: Optional[str] = Field(None, description="Lease expiration date. Format the date to YYYY-MM-DD. If Month to Month rent, put MTM.")
    lease_structure_type: Optional[str] = Field(None, description="Specific recovery profile applied to this tenant: NNN, NN, Gross, etc.")

    # Escallation Steps & Extensions
    rent_increases: Optional[str] = Field(None, description="Verbatim steps or escalation schedules text (e.g., '10% every 5 years', '3% annual bumps').")
    renewal_options: Optional[str] = Field(None, description="Contractual options text to extend beyond maturity (e.g., 'Three 5-Year options at Fair Market Value').")

class RentRollReportPerBuilding(BaseModel):
    """Rent roll of one building."""

    building_name: Optional[str] = Field(None, description="The building name or full address for which the rent roll refers to.")
    number_tenants_in_building:  Optional[int] = Field(1, description="Total number of tenants in the building. Give number of units if multi units. For hotel give None. A vacancy counts for 1.")
    rows: Optional[List[RentRollRow]] = Field(default_factory=list, description="Rent roll of one building, as of today. Each Row being one unit or tenant. Vacancy count as one row.")

class RentRollReport(Confidence):
    """Rent roll of all building."""

    rows: Optional[List[RentRollReportPerBuilding]] = Field(default_factory=list, description="Rent roll of each building, as of today. Each Row being one full rent roll of a building.")

# ==========================================
# 3. FINANCIAL STATEMENTS (COMBINED & DUAL-COLUMN)
# ==========================================
class StandardKPI(BaseModel):
    
    """Normalizes typical cash flow arrays across commercial real estate asset models."""
    
    financial_year: str = Field(..., description="Year of financial statement (e.g., '2025', 'Current', 'Year 1').")
    
    # --- INCOME STREAMS ---
    gross_potential_rent: Optional[float] = Field(None, description="Total contractual baseline rents if 100% of physical space were leased at market rates.")
    expense_reimbursements: Optional[float] = Field(None, description="CAM, tax, and insurance recoveries clawed back from tenants (typical for NNN/retail setup).")
    other_income: Optional[float] = Field(None, description="Alternative programmatic income (parking fees, common space storage fees, sign leases, etc.).")
    gross_scheduled_income: Optional[float] = Field(None, description="Sum of Gross Potential Rent + Expense Reimbursements + Other Income.")
    
    vacancy_loss: Optional[float] = Field(None, description="Underwritten deduction value accounting for expected vacancy gaps and collection risk defaults.")
    effective_gross_income: Optional[float] = Field(None, description="Net operating revenues: Gross Scheduled Income minus Vacancy Loss.")

    # --- EXPENSES (OpEx Shards) ---
    taxes_property: Optional[float] = Field(None, description="Annual real estate and direct municipal assessment taxes.")
    insurance: Optional[float] = Field(None, description="Commercial general property liability and casualty risk policies.")
    utilities_combined: Optional[float] = Field(None, description="Aggregated utility expenses: Water, gas, power grid, and sanitation services.")
    management_fees: Optional[float] = Field(None, description="Asset and Property Management operational oversight overhead costs.")
    repairs_and_maintenance: Optional[float] = Field(None, description="Day-to-day physical upkeep, mechanical inspections, structural fixes, and landscaping tasks.")
    general_and_administrative: Optional[float] = Field(None, description="Administrative back-office run charges: legal support, print collateral, accounting, compliance.")
    other_operating_expenses: Optional[float] = Field(None, description="Catch-all tracking for items not falling neatly into the major accounts above.")
    total_operating_expenses: Optional[float] = Field(None, description="Sum of all operational expense lines outlaid.")

    # --- BOTTOM LINES & METRICS ---
    net_operating_income: Optional[float] = Field(None, description="Net Operating Income (NOI = Effective Gross Income minus Total Operating Expenses).")
    cap_rate: Optional[float] = Field(None, description="Capitalization Rate percentage calculated on asking price or baseline asset value valuation (e.g., 6.75)")

class FinancialStatementExtraction(Confidence):
    """Enables multi-year side-by-side performance matrix runs across underwriting cycles. Focus only on current and past years. No projection"""
    
    building_address: Optional[str] = Field(None, description="The building name or full address for which the rent roll refers to.")
    financial_cycles: Optional[List[StandardKPI]] = Field(default_factory=list, description="Chronological list of financial statements. Each row is a specific year.")

#### hotel specific 

class HotelYearlyData(BaseModel):
    """Captures absolute dollar amounts ($) and metrics mapped to standard hospitality P&L structures."""

    building_name: Optional[str] = Field(None, description="The building name for which the rent roll refers to.")
    financial_year: Optional[str] = Field(..., description="Year of financial statement (e.g., '2025', 'Current', 'Year 1').")
    occupancy_percentage: Optional[float] = Field(default=None, description="Occupancy rate expressed as a full float percentage (e.g., 74.5 for 74.5%).")
    adr: Optional[float] = Field(default=None, description="Average Daily Rate in USD ($) representing room revenue divided by rooms sold.")
    revpar: Optional[float] = Field(default=None, description="Revenue Per Available Room in USD ($) calculated as ADR multiplied by Occupancy Rate.")

    # --- OPERATING REVENUE ($) ---
    revenue_rooms: Optional[float] = Field(default=None, description="Total gross revenue generated from guest room rentals.")
    revenue_food_and_beverage: Optional[float] = Field(default=None, description="Revenue generated from restaurants, bars, banquets, and room service operations.")
    revenue_other_operated_departments: Optional[float] = Field(default=None, description="Revenue from minor departments like spa, golf, parking, laundry, or retail spaces.")
    revenue_miscellaneous: Optional[float] = Field(default=None, description="Other minor non-departmental revenue streams (e.g., cancellation fees, resort fees).")
    total_operating_revenue: Optional[float] = Field(default=None, description="Gross Operating Revenue. Sum of Rooms, F&B, Other Departments, and Misc Income.")

    expense_rooms: Optional[float] = Field(default=None, description="Direct payroll and line expenses related to rooms (housekeeping, laundry, front desk).")
    expense_food_and_beverage: Optional[float] = Field(default=None, description="Direct cost of goods sold (COGS) and labor for all restaurant and banquet outlets.")
    expense_other_operated_departments: Optional[float] = Field(default=None, description="Direct operational costs tied to running minor profit centers (spa, parking, etc.).")
    total_departmental_expenses: Optional[float] = Field(default=None, description="Sum total of all direct departmental performance costs.")
    total_departmental_profit: Optional[float] = Field(default=None, description="Total Departmental Profit (Total Operating Revenue minus Total Departmental Expenses).")
  
    # --- UNDISTRIBUTED OPERATING EXPENSES ($) ---
    administrative_and_general: Optional[float] = Field(default=None, description="A&G support expenses: Executive payroll, HR, legal fees, accounting, and compliance.")
    information_and_telecom: Optional[float] = Field(default=None, description="IT systems, property management software licenses (PMS), Wi-Fi infra, and phone lines.")
    sales_and_marketing: Optional[float] = Field(default=None, description="Marketing campaigns, commissions, local advertising, and loyalty program costs.")
    franchise_fees: Optional[float] = Field(default=None, description="Contractual royalty and brand flag pipeline distribution fees paid to the franchisor.")
    property_operations_and_maintenance: Optional[float] = Field(default=None, description="POM / Engineering charges: mechanical checks, physical repairs, and grounds maintenance.")
    utilities_combined: Optional[float] = Field(default=None, description="Combined energy footprints: Electricity, water, natural gas, and waste disposal management.")
    
    total_undistributed_expenses: Optional[float] = Field(default=None, description="Sum of all indirect overhead support operational expenses.")
    gross_operating_profit: Optional[float] = Field(default=None, description="GOP (Total Departmental Profit minus Total Undistributed Expenses). Key manager metric.")
    management_fees_total: Optional[float] = Field(default=None, description="Total operational base and incentive fees paid out to the third-party management group.")
    income_before_non_operating: Optional[float] = Field(default=None, description="GOP after management fees (Gross Operating Profit minus Management Fees Total).")
    taxes_property: Optional[float] = Field(default=None, description="Real estate, personal property, and direct municipal assessment taxes.")
    insurance_building: Optional[float] = Field(default=None, description="Commercial general liability, structural property, and casualty insurance premiums.")
    other_fixed_charges: Optional[float] = Field(default=None, description="Equipment lease costs, ground rents, or alternative fixed non-operating items.")
    total_non_operating_expenses: Optional[float] = Field(default=None, description="Sum of property taxes, insurance, and alternative fixed non-operating overhead charges.")
    
    # --- BOTTOM LINES ($) ---
    ebitda: Optional[float] = Field(default=None, description="EBITDA / Adjusted GOP (Income Before Non-Operating minus Total Non-Operating Expenses).")
    replacement_reserve: Optional[float] = Field(default=None, description="Replacement reserve amount.")
    net_operating_income: Optional[float] = Field(default=None, description="Final operational yield baseline: Net Operating Income (EBITDA minus FF&E Replacement Reserve).")

class FinancialStatementExtractionHotel(Confidence):
    """Complete Financial Operating & Income Statement for Hospitality/Hotel Assets."""
    
    financial_cycles: Optional[List[HotelYearlyData]] = Field(default_factory=list, description="Chronological list of financial statements. Each row is a specific year.")

# ==========================================
# 4. PROPERTY CONDITION REPORT
# ==========================================
class Amenity(BaseModel):
    """Amenity description of the property, besides the hotel rooms amenities."""
    name: Optional[str] = Field(None, description="Name of the amenity: pool, gym, spa, meeting rooms, event space, parking.")
    amenity_description: Optional[str] = Field(None, description="Description of the amenity.")
    amenity_size: Optional[int] = Field(None, description="Size in square feet of the amenity.")

class Amenities(Confidence):
    """Amenities of the hotel."""
    amenities: Optional[List[Amenity]] = Field(None, description="List of amenities of the property (ex: pool, gym, spa, meeting rooms, parking, etc.)")

# ==========================================
# 5. Demographics / attractiveness Report
# ==========================================

class PointOfInterest(BaseModel):
    """A point of interest."""
    name: Optional[str] = Field(None, description="Name of the point of interest.")
    distance: Optional[float] = Field(None, description="Distance from the property in miles.")
    description: Optional[str] = Field(None, description="One sentence description of the point interest and why this is interesting.")

class ZoneAttractiveness(BaseModel):
    """Close points of interest ."""
    zone_attractiveness: Optional[List[PointOfInterest]] = Field(None, description="List of points of interest close to the property.")

class DemographicColumn(BaseModel):
    """Represents a specific demographic catchment area (e.g., 1-Mile Radius, 10-Min Drive Time)."""
    
    radius_label: Optional[str] = Field(None, description="Radius of the statistics around the offer address (e.g., '1-Mile', '5-Mile').")
    total_population: Optional[int] = Field(None, description="Total population within the radius.")
    population_growth_projection: Optional[float] = Field(None, description="Historical or projected population growth rate (ex: +1.2% annually or 5-year projection).")
    total_households: Optional[int] = Field(None, description="Total number of households (foyers) in the radius.")
    
    people_per_household: Optional[float] = Field(None, description="Average number of people per household in the radius.")
    median_age: Optional[float] = Field(None, description="The median age of the population in this radius.")
    average_age: Optional[float] = Field(None, description="The average age of the population in this radius.")
   
    average_household_income: Optional[float] = Field(None, description="Average Household Income in USD (often abbreviated as AHHI).")
    median_household_income: Optional[float] = Field(None, description="Median Household Income in USD.")
    
    percentage_white: Optional[float] = Field(None, description="Percentage of white population in the radius. Deduce from population volume of white amongst total, if possible.")
    percentage_black: Optional[float] = Field(None, description="Percentage of black population in the radius. Deduce from population volume of black amongst total, if possible.")
    percentage_asian: Optional[float] = Field(None, description="Percentage of asian population in the radius. Deduce from population volume of asian amongst total, if possible.")
    percentage_other: Optional[float] = Field(None, description="Percentage of other population in the radius. It should be the remaining % as of 100 - (white + black + asian)")

class MarketDemographicsReport(Confidence):
    """
    Table extracted from the market analysis or demographics page of the OM.
    Captures multi-radius or multi-drive-time data dynamically.
    """
    
    # Liste dynamique des colonnes de rayons (1, 3, 5 miles ou autres)
    area_statistics : Optional[List[DemographicColumn]] = Field(default=[], description="List of demographic metrics broken down by radius.")

# ==========================================
# 6. Auction Information
# ==========================================
class AuctionInformation(Confidence):
    """Information about the auction."""

    auction_date_start: Optional[str] = Field(None, description="Date of the auction start.")
    auction_date_end: Optional[str] = Field(None, description="Date of the auction end.")
    auction_location: Optional[str] = Field(None, description="Location of the auction.")
    auction_type: Optional[str] = Field(None, description="Type of auction: online, in-person, etc.")
    auction_start_bid: Optional[float] = Field(None, description="Start bid of the auction in USD.")
    
    auction_url: Optional[str] = Field(None, description="URL of the auction.")
    auction_has_reserved_price: Optional[bool] = Field(None, description="Whether the auction has a reserved price.")
    auction_reserve_price: Optional[float] = Field(None, description="Reserve price of the auction in USD.")
