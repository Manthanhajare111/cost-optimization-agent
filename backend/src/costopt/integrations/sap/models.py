"""Typed boundaries for the currently trusted SAP sample payloads."""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class FieldglassWorkerCustomFields(BaseModel):
    """CostOpt mapping fields carried by an approved Fieldglass extension."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    costopt_resource_id: str | None = Field(default=None, alias="costoptResourceId")
    supplier_id: str | None = Field(default=None, alias="supplierId")
    squad_id: str | None = Field(default=None, alias="squadId")
    current_location_id: str | None = Field(default=None, alias="currentLocationId")
    skill: str | None = None
    current_rate: float | None = Field(default=None, ge=0, alias="currentRate")
    pii_access: bool = Field(default=False, alias="piiAccess")
    availability: str | None = None


class FieldglassWorkerPayload(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    first_name: str | None = Field(default=None, alias="firstName")
    last_name: str | None = Field(default=None, alias="lastName")
    email: str | None = None
    city: str | None = None
    state_province: str | None = Field(default=None, alias="stateProvince")
    country: str | None = None
    postal_code: str | None = Field(default=None, alias="postalCode")
    username: str = Field(min_length=1)
    role: str | None = None
    worker_custom_fields: FieldglassWorkerCustomFields = Field(
        default_factory=FieldglassWorkerCustomFields,
        alias="workerCustomFields",
    )


class FieldglassBusinessUnitPayload(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    code: str = Field(min_length=1, alias="Code")
    name: str = Field(min_length=1, alias="Name")
    parent_business_unit: str | None = Field(default=None, alias="Parent Business Unit")
    legal_entity: str | None = Field(default=None, alias="Legal Entity")
    resource_coordinator_required: str | None = Field(
        default=None,
        alias="Resource Coordinator Required Flag",
    )
    distributor_required: str | None = Field(default=None, alias="Distributor Required Flag")


class FieldglassBusinessUnitResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    headers: dict[str, object] = Field(default_factory=dict)
    data: list[FieldglassBusinessUnitPayload] = Field(default_factory=list)


class AribaMoneyPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    amount: Decimal | None = None
    currency_code: str | None = Field(default=None, alias="currencyCode")
    currency: str | None = None

    @property
    def resolved_currency(self) -> str | None:
        value = self.currency_code or self.currency
        return value.upper() if value else None


class AribaPurchaseOrderPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    document_number: str = Field(min_length=1, alias="documentNumber")
    supplier_name: str | None = Field(default=None, alias="supplierName")
    supplier_anid: str | None = Field(default=None, alias="supplierANID")
    vendor_id: str | None = Field(default=None, alias="vendorId")
    buyer_anid: str | None = Field(default=None, alias="buyerANID")
    customer_name: str | None = Field(default=None, alias="customerName")
    po_amount: AribaMoneyPayload | None = Field(default=None, alias="poAmount")
    status: str | None = None
    document_status: str | None = Field(default=None, alias="documentStatus")
    order_date: str | None = Field(default=None, alias="orderDate")
    payload_id: str | None = Field(default=None, alias="payloadId")


class AribaPurchaseOrderResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    content: list[AribaPurchaseOrderPayload] = Field(default_factory=list)
    count: int | None = None
    limit: int | None = None
    offset: int | None = None


class AribaOwnerPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    unique_name: str | None = Field(default=None, alias="uniqueName")


class AribaContractWorkspacePayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    contract_id: str = Field(min_length=1, alias="contractId")
    title: str = Field(min_length=1)
    description: str | None = None
    contract_status: str | None = Field(default=None, alias="contractStatus")
    effective_date: str | None = Field(default=None, alias="effectiveDate")
    expiration_date: str | None = Field(default=None, alias="expirationDate")
    contract_amount: AribaMoneyPayload | None = Field(default=None, alias="contractAmount")
    version: int | None = None
    owner: AribaOwnerPayload | None = None
    active: bool = False
    last_modified: str | None = Field(default=None, alias="lastModified")


class AribaContractWorkspaceResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    value: list[AribaContractWorkspacePayload] = Field(default_factory=list)
    count: int | None = None
    start: int | None = None


class SapImportSummary(BaseModel):
    ingestion_run_id: str
    data_origin: str
    status: str
    endpoint_count: int = Field(ge=0)
    payload_file_count: int = Field(ge=0)
    imported_payload_count: int = Field(ge=0)
    skipped_payload_count: int = Field(ge=0)
    error_count: int = Field(ge=0)
    staged_record_counts: dict[str, int] = Field(default_factory=dict)
    canonical_record_counts: dict[str, int] = Field(default_factory=dict)
    unresolved_record_counts: dict[str, int] = Field(default_factory=dict)


class SapLatestRun(BaseModel):
    ingestion_run_id: str
    requested_source: str
    data_origin: str
    status: str
    endpoint_count: int = Field(ge=0)
    payload_file_count: int = Field(ge=0)
    imported_payload_count: int = Field(ge=0)
    skipped_payload_count: int = Field(ge=0)
    error_count: int = Field(ge=0)
    started_at: str
    completed_at: str | None = None


class SapIngestionStatus(BaseModel):
    configured_endpoint_count: int = Field(ge=0)
    raw_payload_count: int = Field(ge=0)
    payload_counts: dict[str, int] = Field(default_factory=dict)
    origin_counts: dict[str, int] = Field(default_factory=dict)
    staging_counts: dict[str, int] = Field(default_factory=dict)
    canonical_counts: dict[str, int] = Field(default_factory=dict)
    canonicalization_counts: dict[str, int] = Field(default_factory=dict)
    latest_run: SapLatestRun | None = None
