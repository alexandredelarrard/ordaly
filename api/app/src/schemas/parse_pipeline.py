"""Pydantic schemas for LLM / vision extraction (Gemini structured JSON)."""

from typing import Any, List, Optional
from pydantic import BaseModel, Field

class Metainfo(BaseModel):
    page_number: Optional[str] = Field(None, description="Page number where the information comes from in the OM. Can be a list of pages (ex: 1,3,5-7)")

class FinancialLineItem(BaseModel):
    """A generic structure to capture both In-Place and Pro-Forma metrics."""
    in_place_t12: Optional[float] = Field(None, description="Historical or current value (Trailing 12 Months)")
    pro_forma_year1: Optional[float] = Field(None, description="Broker projection for Year 1 / Forward-looking")

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
    total_parcel_size: Optional[float] = Field(None, description="Total parcel size including building and land / parking in inches. If in acres, convert to square feet.")
    
    number_of_units: Optional[int] = Field(None, description="Number of tenants, units, or apartments. Same than rent roll size.")
    
    cap_rate: Optional[FinancialLineItem] = Field(None, description="Cap rate as a percentage (ex: 6.25%)")
    total_net_operating_income: Optional[FinancialLineItem] = Field(None, description="Total net operating income in USD.")

# ==========================================
# 2. RENT ROLL (DEEP VISION / TABLE TIER)
# ==========================================

class RentRollRow(BaseModel):
    """Each line Represents a single item/tenant in a CRE Rent Roll or OM document."""
    
    tenant_name: Optional[str] = Field(None, description="Tenant corporate name (ex: Starbucks, Vacant, Corporate Lease)")
    tenant_headquarters: Optional[str] = Field(None, description="Tenant headquarters address or city name")
    tenant_year_founded: Optional[int] = Field(None, description="Year the tenant was founded.")
    tenant_description: Optional[str] = Field(None, description="Brief 1 to 2 sentences summary of what the tenant is doing")

    unit_size: Optional[int] = Field(None, description="Unit size in square feet (SF)")
    rent_per_sf: Optional[float] = Field(None, description="Current year Yearly Rent per square foot ($/SF/Yr). Common in Retail/Office.")
    unit_rent_price_monthly: Optional[FinancialLineItem] = Field(None, description="Monthly rent price in USD.")
    unit_rent_price_yearly: Optional[FinancialLineItem] = Field(None, description="Yearly rent price in USD.")
    
    unit_type_of_ownership: Optional[str] = Field(None, description="Type of ownership: Fee Simple, Leasehold, Joint Venture, etc.")
    unit_rent_status: Optional[str] = Field(None, description="Status: Vacant, Occupied, Leased but not occupied")
    unit_rent_start_date: Optional[str] = Field(None, description="Lease commencement date")
    unit_rent_end_date: Optional[str] = Field(None, description="Lease expiration date")
    unit_lease_type: Optional[str] = Field(None, description="Lease structure: NNN, NN, Modified Gross, Gross, FSG")
    
    unit_rent_increases: Optional[str] = Field(None, description="Details about rent increases (ex: 3% annually, $0.50/SF in 2027, CPI linked)")
    renewal_options: Optional[str] = Field(None, description="Tenant options to renew (ex: Two 5-year options at market rate)")

class RentRollTableExtraction(Metainfo):
    """The complete wrapper for parsing entire Rent Roll tables."""
    rows: List[RentRollRow] = Field(default=[], description="List of all tenants extracted from the rent roll. If no rent roll, check if possible to recreate based on multiple pages in the OM document.")

# ==========================================
# 3. FINANCIAL STATEMENTS (COMBINED & DUAL-COLUMN)
# ==========================================
class FinancialStatementExtraction(Metainfo):
    """
    Complete Financial Operating & Income Statement.
    Captures both revenues and expenses side-by-side (In-Place vs Pro-Forma).
    """
    # --- REVENUES (Income) ---
    gross_potential_rent: Optional[FinancialLineItem] = Field(None, description="Gross potential rent (GPR)")
    vacancy_and_collection_loss: Optional[FinancialLineItem] = Field(None, description="Vacancy loss, often a % or absolute negative USD")
    other_income: Optional[FinancialLineItem] = Field(None, description="Total other income (parking, laundry, storage, etc.)")
    effective_gross_income: Optional[FinancialLineItem] = Field(None, description="Effective Gross Income (EGI)")

    # --- EXPENSES (OpEx) ---
    taxes: Optional[FinancialLineItem] = Field(None, description="Real Estate / Property Taxes")
    insurance: Optional[FinancialLineItem] = Field(None, description="Property Insurance")
    
    # Regrouper les utilities évite que le LLM invente des ventilations arbitraires
    utilities_total: Optional[FinancialLineItem] = Field(None, description="Total Utilities (Water, Electric, Gas, Trash combined)")
    
    management_fee: Optional[FinancialLineItem] = Field(None, description="Property Management fees")
    repair_and_maintenance: Optional[FinancialLineItem] = Field(None, description="Repairs, maintenance, and turnover costs")
    # AJOUT CLÉ : Les frais administratifs et marketing (G&A)
    general_and_administrative: Optional[FinancialLineItem] = Field(None, description="Admin, legal, marketing, and payroll expenses")
    
    total_operating_expenses: Optional[FinancialLineItem] = Field(None, description="Total Operating Expenses (OpEx)")
    
    # --- BOTTOM LINE --- NOI = EGI - Operating Expenses
    net_operating_income: Optional[FinancialLineItem] = Field(None, description="Net Operating Income (NOI)")

# ==========================================
# 4. PROPERTY CONDITION REPORT
# ==========================================
class PropertyConditionReport(Metainfo):
    """Technical and physical structural constraints from the OM text."""

    year_built: Optional[int] = Field(None, description="Year built original")
    year_renovated: Optional[int] = Field(None, description="Year of last major renovation, 'None' if blank")
    
    construction_type: Optional[str] = Field(None, description="Construction type: wood frame, masonry, steel, concrete tilt-up")
    roof_condition: Optional[str] = Field(None, description="Roof condition notes or rating")
    roof_age: Optional[int] = Field(None, description="Roof age in years or date of last replacement")
    hvac_system_condition: Optional[str] = Field(None, description="HVAC details: Age, central vs individual units, tenant vs landlord responsibility")
    parking_spaces: Optional[int] = Field(None, description="Total number of stalls and/or parking ratio (ex: 4.1 per 1,000 SF)")
    zoning_urban: Optional[str] = Field(None, description="Official zoning code (ex: C-3, M-1, GR) and overlay if any")
    # AJOUT CLÉ : Les "CapEx immédiats" mentionnés par le broker
    deferred_maintenance: Optional[str] = Field(None, description="Any explicit mention of immediate repairs needed (Deferred Maintenance)")

# ==========================================
# 5. Demographics Report
# ==========================================

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

    vehicles_per_day: Optional[int] = Field(None, description="Average number of vehicles per day in the area.")

class MarketDemographicsReport(Metainfo):
    """
    Table extracted from the market analysis or demographics page of the OM.
    Captures multi-radius or multi-drive-time data dynamically.
    """
    
    # Métriques globales du sous-marché (Submarket)
    submarket_vacancy_rate: Optional[float] = Field(None, description="Average vacancy rate of the specific submarket/neighborhood for this asset type (ex: 4.5%).")
    submarket_market_rent: Optional[float] = Field(None, description="Average market rent in the neighborhood (ex: $25/SF/Yr or $1,800/mo for multifamily).")
    
    # Liste dynamique des colonnes de rayons (1, 3, 5 miles ou autres)
    catchment_areas: List[DemographicColumn] = Field(default=[], description="List of demographic metrics broken down by radius or drive time columns found in the OM.")


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


def metadata_to_flat_dict(m: MetadataFromText) -> dict[str, Any]:
    return {k: v for k, v in m.model_dump().items() if v is not None and str(v).strip()}


def combined_text_extractions_flat(
    extractions: dict[str, Any | None],
) -> dict[str, Any]:
    """
    Merge outputs from parallel text-LLM schema calls into one dict.
    ``metadata_from_text`` fields stay unprefixed; other schemas use
    ``{schema_key}__{field}`` keys so names stay unique.
    """
    out: dict[str, Any] = {}
    meta_raw = extractions.get("metadata_from_text")
    if meta_raw and isinstance(meta_raw, dict):
        out.update(metadata_to_flat_dict(MetadataFromText.model_validate(meta_raw)))

    for name, payload in extractions.items():
        if name == "metadata_from_text" or payload is None:
            continue
        if not isinstance(payload, dict):
            continue
        prefix = f"{name}__"
        for k, v in payload.items():
            out[prefix + k] = v
    return out