"""Testes para emr_instances.sources.pricing"""

from __future__ import annotations

import json
import logging
from typing import Any
from unittest.mock import MagicMock

import pytest

from emr_instances.sources import pricing


def _product(instance_type: str, usd: str, **attrs: str) -> dict[str, Any]:
    """Produto da Price List API com os atributos que a coleta lê."""
    return {
        "product": {
            "attributes": {
                "instanceType": instance_type,
                "physicalProcessor": "AWS Graviton4 Processor",
                "instanceFamily": "Memory optimized",
                "normalizationSizeFactor": "32",
                **attrs,
            }
        },
        "terms": {
            "OnDemand": {
                "sku.TERM1": {
                    "priceDimensions": {"dim1": {"pricePerUnit": {"USD": usd}}}
                }
            }
        },
    }


def test_extract_on_demand_usd_success() -> None:
    """Test extração de preço on-demand válido."""
    product: dict[str, object] = {
        "terms": {
            "OnDemand": {
                "sku.TERM1": {
                    "priceDimensions": {"dim1": {"pricePerUnit": {"USD": "0.123456"}}}
                }
            }
        }
    }
    price = pricing._extract_on_demand_usd(product)
    assert price == 0.123456


def test_extract_on_demand_usd_missing() -> None:
    """Test retorna None quando não há preço."""
    product: dict[str, object] = {"terms": {}}
    price = pricing._extract_on_demand_usd(product)
    assert price is None

    product2: dict[str, object] = {"terms": {"OnDemand": {}}}
    price2 = pricing._extract_on_demand_usd(product2)
    assert price2 is None


def test_on_demand_prices() -> None:
    """Test obtenção de preços on-demand com paginação."""
    mock_pricing = MagicMock()
    mock_paginator = MagicMock()
    mock_pricing.get_paginator.return_value = mock_paginator
    mock_paginator.paginate.return_value = [
        {
            "PriceList": [
                json.dumps(_product("r8gd.4xlarge", "1.8616")),
                json.dumps(_product("r8gd.8xlarge", "3.7232")),
            ]
        }
    ]

    result = pricing.on_demand_prices(mock_pricing)
    assert result["r8gd.4xlarge"]["usd_hour"] == 1.8616
    assert result["r8gd.8xlarge"]["usd_hour"] == 3.7232


def test_on_demand_prices_atributos_de_catalogo() -> None:
    """Os três campos que só a Price List tem entram junto com o preço."""
    mock_pricing = MagicMock()
    mock_paginator = MagicMock()
    mock_pricing.get_paginator.return_value = mock_paginator
    mock_paginator.paginate.return_value = [
        {"PriceList": [json.dumps(_product("r8gd.4xlarge", "1.8616"))]}
    ]

    product = pricing.on_demand_prices(mock_pricing)["r8gd.4xlarge"]
    assert product["processor_name"] == "AWS Graviton4 Processor"
    assert product["family_category"] == "Memory optimized"
    assert product["normalization_factor"] == 32


def test_on_demand_prices_atributos_ausentes() -> None:
    """Produto sem os atributos de catálogo ainda entra, com None nos três."""
    mock_pricing = MagicMock()
    mock_paginator = MagicMock()
    mock_pricing.get_paginator.return_value = mock_paginator
    product_raw: dict[str, Any] = {
        "product": {"attributes": {"instanceType": "m5.large"}},
        "terms": {
            "OnDemand": {
                "sku.TERM1": {
                    "priceDimensions": {"dim1": {"pricePerUnit": {"USD": "0.096"}}}
                }
            }
        },
    }
    mock_paginator.paginate.return_value = [{"PriceList": [json.dumps(product_raw)]}]

    product = pricing.on_demand_prices(mock_pricing)["m5.large"]
    assert product["usd_hour"] == 0.096
    assert product["processor_name"] is None
    assert product["family_category"] is None
    assert product["normalization_factor"] is None


def test_parse_normalization_factor() -> None:
    """Fator inteiro sai int (JSON `32`), fracionário sai float, "NA" vira None."""
    assert pricing._parse_normalization_factor("32") == 32
    assert isinstance(pricing._parse_normalization_factor("32"), int)
    assert pricing._parse_normalization_factor("0.25") == 0.25
    assert pricing._parse_normalization_factor("NA") is None
    assert pricing._parse_normalization_factor(None) is None


def _emr_product(instance_type: str, usd: str, **attrs: str) -> dict[str, Any]:
    """Produto da Price List do EMR: tipo, preço por instância-hora e software."""
    attributes = {"instanceType": instance_type, "softwareType": "EMR", **attrs}
    return {
        "product": {"attributes": attributes},
        "terms": {
            "OnDemand": {
                "sku.TERM1": {
                    "priceDimensions": {"dim1": {"pricePerUnit": {"USD": usd}}}
                }
            }
        },
    }


def _pricing_with(products: list[dict[str, Any]]) -> tuple[MagicMock, MagicMock]:
    """Client Pricing fake cujo paginator devolve os produtos numa página só."""
    mock_pricing = MagicMock()
    paginator = MagicMock()
    mock_pricing.get_paginator.return_value = paginator
    paginator.paginate.return_value = [
        {"PriceList": [json.dumps(product) for product in products]}
    ]
    return mock_pricing, paginator


def test_emr_fees_consulta_o_servico_do_emr_na_regiao() -> None:
    """A varredura é do serviço ElasticMapReduce, filtrada pela região."""
    mock_pricing, paginator = _pricing_with([_emr_product("m5.xlarge", "0.048")])

    pricing.emr_fees(mock_pricing)

    kwargs = paginator.paginate.call_args.kwargs
    assert kwargs["ServiceCode"] == "ElasticMapReduce"
    assert {
        "Type": "TERM_MATCH",
        "Field": "regionCode",
        "Value": "sa-east-1",
    } in kwargs["Filters"]


def test_emr_fees_taxa_varia_por_tipo() -> None:
    """A taxa é por tipo de instância; não é um valor único nem proporcional."""
    mock_pricing, _ = _pricing_with(
        [
            _emr_product("m5.xlarge", "0.048"),
            _emr_product("m5.24xlarge", "0.27"),
            _emr_product("c5.xlarge", "0.04"),
        ]
    )

    assert pricing.emr_fees(mock_pricing) == {
        "m5.xlarge": 0.048,
        "m5.24xlarge": 0.27,
        "c5.xlarge": 0.04,
    }


def test_emr_fees_ignora_outro_software_zero_e_produto_sem_tipo() -> None:
    """MapR, preço zero e produto sem `instanceType` não viram taxa do EMR."""
    mock_pricing, _ = _pricing_with(
        [
            _emr_product("m5.xlarge", "0.048", softwareType="EMR"),
            _emr_product("m5.xlarge", "0.200", softwareType="MapR-M5"),
            _emr_product("c5.xlarge", "0.0"),
            {"product": {"attributes": {}}, "terms": {}},
        ]
    )

    assert pricing.emr_fees(mock_pricing) == {"m5.xlarge": 0.048}


def test_emr_fees_conflito_deixa_o_tipo_de_fora(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Dois preços diferentes para o mesmo tipo: não escolhe, avisa no log."""
    mock_pricing, _ = _pricing_with(
        [
            _emr_product("m5.xlarge", "0.048"),
            _emr_product("m5.xlarge", "0.060"),
            _emr_product("c5.xlarge", "0.04"),
        ]
    )

    with caplog.at_level(logging.WARNING):
        result = pricing.emr_fees(mock_pricing)

    assert result == {"c5.xlarge": 0.04}
    assert "m5.xlarge" in caplog.text


def test_emr_fees_mesmo_preco_repetido_nao_e_conflito() -> None:
    """O mesmo preço em dois produtos (ex.: duas SKUs iguais) conta uma vez."""
    mock_pricing, _ = _pricing_with(
        [_emr_product("m5.xlarge", "0.048"), _emr_product("m5.xlarge", "0.048")]
    )

    assert pricing.emr_fees(mock_pricing) == {"m5.xlarge": 0.048}
