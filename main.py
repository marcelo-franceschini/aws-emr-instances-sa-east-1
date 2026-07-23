"""Gera um JSON com as instâncias EMR suportadas em São Paulo (sa-east-1),
incluindo preço on-demand e preço spot (Linux/UNIX).

Fontes:
- Instâncias:  emr:ListSupportedInstanceTypes
- On-demand:   pricing:GetProducts (Price List API — endpoint em us-east-1)
- Spot:        ec2:DescribeSpotPriceHistory
"""

import argparse
import json
from datetime import datetime, timezone

import boto3

REGION = "sa-east-1"
# A Price List API só existe em alguns endpoints; us-east-1 é o mais comum.
PRICING_ENDPOINT_REGION = "us-east-1"
OUTPUT_FILE = "instances_sa-east-1.json"


# --------------------------------------------------------------------------- #
# Instâncias suportadas pelo EMR
# --------------------------------------------------------------------------- #
def latest_release_label(emr) -> str:
    """Retorna o release label mais recente do EMR disponível na região."""
    labels: list[str] = []
    marker = None
    while True:
        kwargs = {"Marker": marker} if marker else {}
        response = emr.list_release_labels(**kwargs)
        labels.extend(response.get("ReleaseLabels", []))
        marker = response.get("Marker")
        if not marker:
            break
    return max(labels, key=_version_key)


def _version_key(label: str) -> tuple[int, ...]:
    version = label.removeprefix("emr-")
    return tuple(int(part) for part in version.split(".") if part.isdigit())


def supported_instance_types(emr, release_label: str) -> list[dict]:
    """Retorna todos os tipos de instância suportados para um release label."""
    instance_types: list[dict] = []
    marker = None
    while True:
        kwargs = {"ReleaseLabel": release_label}
        if marker:
            kwargs["Marker"] = marker
        response = emr.list_supported_instance_types(**kwargs)
        instance_types.extend(response.get("SupportedInstanceTypes", []))
        marker = response.get("Marker")
        if not marker:
            break
    return instance_types


# --------------------------------------------------------------------------- #
# Preço on-demand (Price List API)
# --------------------------------------------------------------------------- #
def on_demand_prices(pricing) -> dict[str, float]:
    """Mapeia {instance_type: preço USD/hora on-demand} para a região inteira.

    Faz uma única varredura paginada em vez de uma chamada por instância.
    """
    prices: dict[str, float] = {}
    paginator = pricing.get_paginator("get_products")
    pages = paginator.paginate(
        ServiceCode="AmazonEC2",
        Filters=[
            {"Type": "TERM_MATCH", "Field": "regionCode", "Value": REGION},
            {"Type": "TERM_MATCH", "Field": "operatingSystem", "Value": "Linux"},
            {"Type": "TERM_MATCH", "Field": "tenancy", "Value": "Shared"},
            {"Type": "TERM_MATCH", "Field": "preInstalledSw", "Value": "NA"},
            {"Type": "TERM_MATCH", "Field": "capacitystatus", "Value": "Used"},
        ],
    )
    for page in pages:
        for raw in page["PriceList"]:
            product = json.loads(raw)
            instance_type = product["product"]["attributes"].get("instanceType")
            price = _extract_on_demand_usd(product)
            if instance_type and price is not None:
                prices[instance_type] = price
    return prices


def _extract_on_demand_usd(product: dict) -> float | None:
    """Extrai o preço USD/hora dos termos OnDemand de um produto."""
    on_demand = product.get("terms", {}).get("OnDemand", {})
    for term in on_demand.values():
        for dimension in term.get("priceDimensions", {}).values():
            usd = dimension.get("pricePerUnit", {}).get("USD")
            if usd is not None:
                return round(float(usd), 6)
    return None


# --------------------------------------------------------------------------- #
# Preço spot (menor entre as AZs)
# --------------------------------------------------------------------------- #
def spot_prices(ec2) -> dict[str, dict]:
    """Mapeia {instance_type: {"usd_hour": menor preço, "az": AZ}}.

    Uma única varredura pega o preço spot atual de todas as instâncias/AZs;
    fica com o menor preço entre as AZs e registra em qual AZ estava.
    """
    cheapest: dict[str, dict] = {}
    paginator = ec2.get_paginator("describe_spot_price_history")
    pages = paginator.paginate(
        StartTime=datetime.now(timezone.utc),  # só o preço atualmente vigente
        ProductDescriptions=["Linux/UNIX"],
    )
    for page in pages:
        for entry in page["SpotPriceHistory"]:
            instance_type = entry["InstanceType"]
            price = float(entry["SpotPrice"])
            current = cheapest.get(instance_type)
            if current is None or price < current["usd_hour"]:
                cheapest[instance_type] = {
                    "usd_hour": round(price, 6),
                    "az": entry["AvailabilityZone"],
                }
    return cheapest


# --------------------------------------------------------------------------- #
def build_records(instances: list[dict], on_demand: dict, spot: dict) -> list[dict]:
    records = []
    for instance in sorted(instances, key=lambda i: i["Type"]):
        instance_type = instance["Type"]
        memory = instance.get("MemoryGB")
        records.append(
            {
                "instance_type": instance_type,
                "vcpu": instance.get("VCPU"),
                "memory_gb": round(memory, 2) if isinstance(memory, (int, float)) else None,
                "architecture": instance.get("Architecture"),
                "on_demand_usd_hour": on_demand.get(instance_type),
                "spot": spot.get(instance_type),
            }
        )
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--release-label",
        help="Release label do EMR (ex.: emr-7.13.0). "
        "Se omitido, usa o mais recente disponível.",
    )
    parser.add_argument(
        "--output",
        default=OUTPUT_FILE,
        help=f"Arquivo JSON de saída (padrão: {OUTPUT_FILE}).",
    )
    args = parser.parse_args()

    emr = boto3.client("emr", region_name=REGION)
    ec2 = boto3.client("ec2", region_name=REGION)
    pricing = boto3.client("pricing", region_name=PRICING_ENDPOINT_REGION)

    release_label = args.release_label or latest_release_label(emr)
    print(f"Coletando instâncias EMR ({release_label}) em {REGION}...")
    instances = supported_instance_types(emr, release_label)
    print(f"  {len(instances)} tipos de instância")

    print("Coletando preços on-demand (Price List API)...")
    on_demand = on_demand_prices(pricing)
    print(f"  {len(on_demand)} preços on-demand")

    print("Coletando preços spot (menor entre as AZs)...")
    spot = spot_prices(ec2)
    print(f"  {len(spot)} preços spot")

    records = build_records(instances, on_demand, spot)
    payload = {
        "region": REGION,
        "release_label": release_label,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "instance_count": len(records),
        "instances": records,
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")

    missing_od = sum(1 for r in records if r["on_demand_usd_hour"] is None)
    missing_spot = sum(1 for r in records if r["spot"] is None)
    print(f"\nSalvo em {args.output}")
    print(f"  sem preço on-demand: {missing_od}")
    print(f"  sem preço spot:      {missing_spot}")


if __name__ == "__main__":
    main()
