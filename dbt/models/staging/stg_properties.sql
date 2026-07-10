select
    pid,
    neighborhood,
    bldg_type,
    house_style,
    ms_zoning,
    year_built,
    overall_qual,
    overall_cond,
    gr_liv_area,
    total_bsmt_sf,
    full_bath,
    half_bath,
    bedroom_abvgr,
    sale_price,
    lat,
    lng
from {{ source('trident_operational', 'properties') }}
