from ..utils.size import format_size


def summarize_scan_results(scans: dict[str, dict]) -> dict:
    total = 0
    categories = []
    for name, data in scans.items():
        sz = data.get("total_size", 0)
        total += sz
        categories.append({
            "category": name,
            "total_size": sz,
            "total_size_human": format_size(sz),
            "item_count": data.get("item_count", 0),
        })

    categories.sort(key=lambda x: x["total_size"], reverse=True)

    return {
        "grand_total": total,
        "grand_total_human": format_size(total),
        "categories": categories,
        "details": scans,
    }
