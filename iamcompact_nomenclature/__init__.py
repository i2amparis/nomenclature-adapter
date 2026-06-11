# Import _region_adjustments to make sure region attributes are adjusted as
# needed before the definitions are loaded.
# Change: Don't adjust for regions yet. Since the ISO3 code check in
# `nomenclature.RegionCode` happens directly against the ISO2 codes in
# `pycountry.countries`, making adjustments here won't be enough. Need to wait
# until the `nomenclature` code is changed, if ever.
# from . import _region_adjustments

from .default_definitions import (
    dimensions,
    get_dsd,
    get_region_processor,
    get_validation_profiles,
)

from . import validation
from . import aggregation
from . import mapping

def check_var_aggregates(data, profile_name='iamcompact-default'):
    
    # Get DSD dynamically using the requested profile
    dsd = get_dsd(profile_name=profile_name) 
    return aggregation.check_var_aggregates(data, dsd=dsd)


def check_region_aggregates(data, profile_name='iamcompact-default'):
    
    # Get DSD dynamically using the requested profile
    dsd = get_dsd(profile_name=profile_name) 
    
    # Get the region processor 
    processor = get_region_processor(profile_name=profile_name)
    
    return aggregation.check_region_aggregates(
        data,
        dsd=dsd,
        processor=processor,
    )
    
