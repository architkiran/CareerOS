from careeros.modules.sources.adapters.ashby import AshbyAdapter
from careeros.modules.sources.adapters.base import Adapter, InvalidPayloadError
from careeros.modules.sources.adapters.community import CommunityFeedAdapter
from careeros.modules.sources.adapters.greenhouse import GreenhouseAdapter
from careeros.modules.sources.adapters.lever import LeverAdapter
from careeros.modules.sources.adapters.public_boards import JobicyAdapter, RemotiveAdapter
from careeros.modules.sources.adapters.smartrecruiters import SmartRecruitersAdapter
from careeros.modules.sources.adapters.workday import WorkdayAdapter
from careeros.modules.sources.adapters.wwr import WWRAdapter

ADAPTERS: dict[str, Adapter] = {
    "greenhouse": GreenhouseAdapter(),
    "lever": LeverAdapter(),
    "ashby": AshbyAdapter(),
    "smartrecruiters": SmartRecruitersAdapter(),
    "remotive": RemotiveAdapter(),
    "jobicy": JobicyAdapter(),
    "wwr": WWRAdapter(),
    "workday": WorkdayAdapter(),
    "community": CommunityFeedAdapter(),
}

__all__ = ["ADAPTERS", "Adapter", "InvalidPayloadError"]
