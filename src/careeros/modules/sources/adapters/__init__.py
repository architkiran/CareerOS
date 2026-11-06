from careeros.modules.sources.adapters.ashby import AshbyAdapter
from careeros.modules.sources.adapters.base import Adapter, InvalidPayloadError
from careeros.modules.sources.adapters.greenhouse import GreenhouseAdapter
from careeros.modules.sources.adapters.lever import LeverAdapter
from careeros.modules.sources.adapters.smartrecruiters import SmartRecruitersAdapter

ADAPTERS: dict[str, Adapter] = {
    "greenhouse": GreenhouseAdapter(),
    "lever": LeverAdapter(),
    "ashby": AshbyAdapter(),
    "smartrecruiters": SmartRecruitersAdapter(),
}

__all__ = ["ADAPTERS", "Adapter", "InvalidPayloadError"]
