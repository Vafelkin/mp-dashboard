"""
Pydantic-схемы для валидации данных, получаемых от внешних API.
"""
from pydantic import BaseModel, Field
from typing import List, Optional

# Схемы для Wildberries API

class WBStockItem(BaseModel):
    quantity: int
    in_way_to_client: int = Field(0, alias="inWayToClient")
    in_way_from_client: int = Field(0, alias="inWayFromClient")
    warehouse_name: str = Field(..., alias="warehouseName")
    supplier_article: str = Field(..., alias="supplierArticle")
    nm_id: int = Field(..., alias="nmId")

class WBOrderItem(BaseModel):
    date: str
    srid: str
    supplier_article: str = Field(..., alias="supplierArticle")
    warehouse_name: str = Field(..., alias="warehouseName")
    oblast_okrug_name: str = Field(..., alias="oblastOkrugName")
    is_cancel: bool = Field(False, alias="isCancel")

class WBSaleItem(BaseModel):
    date: str
    srid: str
    supplier_article: str = Field(..., alias="supplierArticle")
    warehouse_name: str = Field(..., alias="warehouseName")
    oblast_okrug_name: str = Field(..., alias="oblastOkrugName")
    is_cancel: bool = Field(False, alias="isCancel")


# Схемы для Ozon API

class OzonStockItem(BaseModel):
    available_stock_count: int
    transit_stock_count: int
    warehouse_name: str
    offer_id: str
    ads: float = 0.0
    idc: float = 0.0

class OzonStockResponse(BaseModel):
    items: List[OzonStockItem]

class OzonPostingProduct(BaseModel):
    quantity: int
    offer_id: str

class OzonPosting(BaseModel):
    products: List[OzonPostingProduct]

class OzonPostingResponse(BaseModel):
    result: List[OzonPosting]

class OzonReturnProduct(BaseModel):
    quantity: int
    offer_id: str

class OzonReturnPosting(BaseModel):
    products: List[OzonReturnProduct]

class OzonReturnResponse(BaseModel):
    result: List[OzonReturnPosting]
    
class OzonCashbox(BaseModel):
    balance: float
    currency_code: str

class OzonCashboxResponse(BaseModel):
    result: List[OzonCashbox]
