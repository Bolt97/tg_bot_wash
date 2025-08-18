# models/washes.py
from __future__ import annotations
from typing import Any, Dict, List, Optional, Literal
from datetime import date
from pydantic import BaseModel, Field, TypeAdapter

StatusType = Literal["ok", "alarm", "error", "offline", "unknown"]
OnlineType = Literal["ok", "offline", "unknown"]
ModuleVisibility = Literal["all", "internal", "hidden"]

class ProfileEntry(BaseModel):
    type: str
    value: Dict[str, Any]

class PackageInfo(BaseModel):
    name: str
    generation: int

class SoftwareHash(BaseModel):
    slideshow: Optional[Any] = None
    package: PackageInfo

class Software(BaseModel):
    hash: SoftwareHash
    apps: List[Any]

class Module(BaseModel):
    id: str
    name: str
    full_name: str
    status: StatusType
    status_changed_at: int
    status_changed_at_offset_s: int
    source: str
    text: Optional[str] = None
    visibility: ModuleVisibility
    details: Optional[Any] = None
    modules: List[Any] = Field(default_factory=list)
    external: bool
    dirty: Optional[str] = None  # встречается "local" / null

class DeviceStatus(BaseModel):
    id: int
    type: StatusType
    online_type: OnlineType
    modules: Optional[Any] = None
    recorded_at: int

class WashItem(BaseModel):
    id: int
    tid: str
    tid2: Optional[str] = None
    inventory_id: str
    project: int
    software_profile: Optional[Any] = None
    software_package: Optional[str] = None

    vending: Optional[Any] = None
    vending_profile: Optional[Any] = None
    slideshow: Optional[Any] = None

    city: str
    address: str
    location_name: str

    customer: str
    order_id: str

    vending_model: Optional[Any] = None
    comment: Optional[str] = None
    product_list: Optional[Any] = None

    tz: str
    shipped_on: date

    last_trx_at: int
    last_trx_offset_s: int

    profile: Dict[str, ProfileEntry]
    tags: Optional[Any] = None

    modules: List[Module]
    profiles: Dict[str, int]

    trx_count: int
    status: DeviceStatus
    software: Software

    sn: str

# Парсер массива WashItem
WashesAdapter = TypeAdapter(List[WashItem])