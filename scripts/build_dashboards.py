import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROM = {"type": "prometheus", "uid": "prometheus"}
PG = {"type": "grafana-postgresql-datasource", "uid": "postgres"}


def panel(title, query, unit="short", kind="timeseries", sql=False, description=""):
    target = {"refId": "A", "datasource": PG if sql else PROM}
    if sql:
        target.update(rawSql=query, format="time_series" if kind == "timeseries" else "table", rawQuery=True, editorMode="code")
    else:
        target.update(expr=query, legendFormat="{{version}}" if "model_" in query else "{{__name__}} {{device}} {{stage}}", range=True)
    return {"title": title, "type": kind, "datasource": PG if sql else PROM, "description": description, "targets": [target],
            "fieldConfig": {"defaults": {"unit": unit, "color": {"mode": "palette-classic"}, "custom": {"lineWidth": 2, "fillOpacity": 12}}, "overrides": []},
            "options": {"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}}}


def heatmap(title, metric):
    result = panel(title, f"sum by (le) (rate({metric}_bucket[30s]))", kind="heatmap")
    result["targets"][0].update(format="heatmap", legendFormat="{{le}}")
    result["options"] = {"calculate": False, "cellGap": 1, "color": {"mode": "scheme", "scheme": "Spectral", "steps": 64}, "yAxis": {"axisLabel": "score", "min": 0, "max": 1}, "tooltip": {"show": True}}
    return result


def save(uid, title, panels, variables=None, annotations=None):
    for index, item in enumerate(panels):
        item["id"] = index + 1
        item.setdefault("gridPos", {"x": (index % 2) * 12, "y": (index // 2) * 9, "w": 12, "h": 9})
    dashboard = {"uid": uid, "title": title, "schemaVersion": 40, "version": 1, "editable": True,
                 "tags": ["fraud", "hw05"], "timezone": "browser", "refresh": "5s", "time": {"from": "now-15m", "to": "now"},
                 "panels": panels, "templating": {"list": variables or []}, "annotations": {"list": annotations or []}}
    (ROOT / "grafana/dashboards" / f"{uid}.json").write_text(json.dumps(dashboard, ensure_ascii=False, indent=2) + "\n")


annotation = {"name": "Новая модель", "datasource": PROM, "enable": True, "iconColor": "#FFB357",
              "expr": "fraud_model_loaded_timestamp_seconds > (time() - 30)", "step": "1s",
              "titleFormat": "Модель {{version}}", "textFormat": "Горячая загрузка {{version}}", "tagKeys": "version"}
scoring_panels = [
    panel("Скорость обработки", "sum(rate(fraud_processed_total[30s]))", "ops"),
    panel("Время обработки · p95", "histogram_quantile(0.95, sum by (le) (rate(fraud_processing_seconds_bucket[30s])))", "s"),
    panel("Доля фрода за минуту", "sum(rate(fraud_flagged_total[1m])) / clamp_min(sum(rate(fraud_processed_total[1m])), 0.001)", "percentunit"),
    heatmap("Распределение скоров во времени", "fraud_score"),
    panel("Возраст события · p95", "histogram_quantile(0.95, sum by (le) (rate(fraud_event_age_seconds_bucket[30s])))", "s", description="Время от создания транзакции до публикации скора. Рост показывает задержку доставки или накопление очереди."),
    panel("Переключение модели · отметка 30 секунд", "fraud_model_loaded_timestamp_seconds > bool (time() - 30)", description="Линия подписана версией; высота 1 сохраняется 30 секунд после горячей загрузки."),
    panel("Число горячих загрузок по версиям", "fraud_model_updates_total", kind="stat"),
    panel("Ошибки обработки", "sum by (stage) (rate(fraud_errors_total[1m]))", "ops"),
    panel("Скоры и доля фрода по версии модели", '''
SELECT model_version AS "Версия", count(*) AS "Скоров",
       avg(fraud_flag)::double precision AS "Доля фрода",
       avg(score) AS "Средний скор"
FROM scores WHERE $__timeFilter(scored_at)
GROUP BY model_version ORDER BY min(scored_at)
''', kind="table", sql=True, description="Результаты из PostgreSQL за выбранный период для всего потока. Сравните версии модели со скоростью и временем обработки Prometheus на этом же экране."),
]
# Keep existing panel IDs so provisioned alerts still link to TPS and fraud share.
scoring_panels[0]["gridPos"] = {"x": 0, "y": 0, "w": 6, "h": 9}
scoring_panels[1]["gridPos"] = {"x": 6, "y": 0, "w": 6, "h": 9}
scoring_panels[-1]["gridPos"] = {"x": 12, "y": 0, "w": 12, "h": 9}
scoring_panels[-1]["fieldConfig"]["overrides"] = [
    {"matcher": {"id": "byName", "options": "Доля фрода"},
     "properties": [{"id": "unit", "value": "percentunit"}]},
]
save("fraud-scoring", "01 · Скоринг потока", scoring_panels, annotations=[annotation])
save("fraud-writer", "02 · Запись результатов", [
    panel("Запись новых скоров", "sum(rate(writer_scores_total[30s]))", "ops"),
    panel("Время записи · p95", "histogram_quantile(0.95, sum by (le) (rate(writer_write_seconds_bucket[30s])))", "s"),
    panel("Выявленный фрод · с запуска writer", "writer_fraud_total", kind="stat"),
    heatmap("Распределение записанных скоров", "writer_score"),
    panel("Повторные доставки", "writer_duplicates_total", kind="stat"),
    panel("Ошибки записи", "rate(writer_errors_total[1m])", "ops"),
])
save("fraud-system", "03 · Ресурсы среды", [
    panel("CPU · занято", '1 - avg(rate(node_cpu_seconds_total{mode="idle"}[30s]))', "percentunit"),
    panel("Память · занято", "1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes", "percentunit"),
    panel("Сеть · приём", 'rate(node_network_receive_bytes_total{device!="lo"}[30s])', "Bps"),
    panel("Сеть · передача", 'rate(node_network_transmit_bytes_total{device!="lo"}[30s])', "Bps"),
    panel("Диск · чтение", 'rate(node_disk_read_bytes_total{device!~"loop.*|ram.*"}[30s])', "Bps"),
    panel("Диск · запись", 'rate(node_disk_written_bytes_total{device!~"loop.*|ram.*"}[30s])', "Bps"),
    panel("Файловая система · занято", '1 - node_filesystem_avail_bytes{fstype!~"tmpfs|overlay|squashfs"} / node_filesystem_size_bytes{fstype!~"tmpfs|overlay|squashfs"}', "percentunit"),
    panel("Доступность сборщиков", "up", kind="stat"),
])
variables = []
for name, label in [("us_state", "Штат"), ("merch", "Мерчант")]:
    query = f"SELECT DISTINCT {name} FROM scores ORDER BY 1"
    variables.append({"name": name, "label": label, "type": "query", "datasource": PG, "query": query, "definition": query,
                      "refresh": 1, "multi": True, "includeAll": True, "current": {"text": "All", "value": "$__all"}, "options": [], "sort": 1})
where = "us_state IN (${us_state:sqlstring}) AND merch IN (${merch:sqlstring})"
window = f"$__timeFilter(scored_at) AND {where}"
density = f"""
WITH selected AS (SELECT least(floor(score * 20)::int, 19) AS bin FROM scores WHERE {window}),
counts AS (SELECT bin, count(*) AS n FROM selected GROUP BY bin)
SELECT to_char(b.bin * 0.05, '0.00') || '–' || to_char((b.bin + 1) * 0.05, '0.00') AS "score",
       coalesce(c.n, 0)::double precision / nullif((SELECT count(*) FROM selected) * 0.05, 0) AS "Плотность"
FROM generate_series(0, 19) b(bin) LEFT JOIN counts c USING (bin) ORDER BY b.bin
"""
tps = f"""
WITH buckets AS (
 SELECT generate_series(to_timestamp(ceil(extract(epoch FROM $__timeFrom()::timestamptz) / 10) * 10),
 to_timestamp(floor(extract(epoch FROM $__timeTo()::timestamptz) / 10) * 10 - 10), interval '10 seconds') AS time
), counts AS (
 SELECT to_timestamp(floor(extract(epoch FROM scored_at) / 10) * 10) AS time, count(*) / 10.0 AS tps
 FROM scores WHERE {window} GROUP BY 1
)
SELECT b.time AS "time", coalesce(c.tps, 0)::double precision AS "TPS" FROM buckets b LEFT JOIN counts c USING (time) ORDER BY 1
"""
category = """
WITH recent AS (SELECT cat_id, fraud_flag FROM scores ORDER BY scored_at DESC, transaction_id DESC LIMIT 1000)
SELECT cat_id, avg(fraud_flag)::double precision AS "Доля фрода" FROM recent GROUP BY cat_id ORDER BY 2 DESC
"""
panels = [
    panel("Скоры и доля фрода по версии модели", f'SELECT model_version AS "Версия", count(*) AS "Скоров", avg(fraud_flag)::double precision AS "Доля фрода", avg(score) AS "Средний скор" FROM scores WHERE {window} GROUP BY model_version ORDER BY min(scored_at)', kind="table", sql=True),
    panel("Плотность скоров · выбранный сегмент", density, kind="barchart", sql=True, description="Оценка плотности: count / (N × 0.05). Площадь столбцов равна 1. Учитываются период, штат и мерчант."),
    panel("TPS · выбранный сегмент", tps, "ops", sql=True, description="Число уникальных транзакций / 10 секунд. Только полные интервалы; пропуски заполнены нулями."),
    panel("Фрод по категории · последние 1000 транзакций", category, "percentunit", "barchart", True, "Общие последние 1000 записей потока независимо от фильтров и периода. Если записей меньше, используются все имеющиеся."),
    panel("Сумма подозрительных транзакций по мерчантам", f'SELECT merch AS "Мерчант", sum(amt * fraud_flag) AS "Подозрительная сумма, USD" FROM scores WHERE {window} GROUP BY merch ORDER BY 2 DESC', "currencyUSD", "barchart", True, "Помогает приоритизировать проверку по денежному объёму. Это сумма помеченных транзакций, а не подтверждённый ущерб."),
    panel("Размер выборки · выбранный сегмент", f'SELECT count(*) AS "Транзакций" FROM scores WHERE {window}', kind="stat", sql=True),
]
for item in panels:
    if item["type"] == "barchart":
        item["options"].update(xTickLabelRotation=-20, showValue="auto", groupWidth=0.8, barWidth=0.9)
save("fraud-business", "04 · Сегменты и бизнес", panels, variables)


def rule(uid, title, expr, threshold, duration, summary, panel_id):
    return {"uid": uid, "title": title, "condition": "C", "for": duration,
            "noDataState": "Alerting", "execErrState": "Error", "isPaused": False,
            "labels": {"team": "fraud", "severity": "warning"},
            "annotations": {"summary": summary, "__dashboardUid__": "fraud-scoring", "__panelId__": str(panel_id)},
            "data": [
                {"refId": "A", "datasourceUid": "prometheus", "relativeTimeRange": {"from": 120, "to": 0},
                 "model": {"refId": "A", "expr": expr, "instant": True, "range": False, "intervalMs": 1000, "maxDataPoints": 43200, "datasource": PROM}},
                {"refId": "C", "datasourceUid": "__expr__", "relativeTimeRange": {"from": 0, "to": 0},
                 "model": {"refId": "C", "type": "threshold", "expression": "A", "datasource": {"type": "__expr__", "uid": "__expr__"},
                           "conditions": [{"type": "query", "evaluator": {"type": "gt", "params": [threshold]}, "operator": {"type": "and"}, "reducer": {"type": "last", "params": []}}]}}
            ]}

rules = {"apiVersion": 1, "groups": [{"orgId": 1, "name": "fraud-stream", "folder": "Fraud monitoring", "interval": "10s", "rules": [
    rule("fraud-high-share", "Высокая доля фрода", "sum(rate(fraud_flagged_total[1m])) / clamp_min(sum(rate(fraud_processed_total[1m])), 0.001)", 0.35, "30s", "Доля помеченных транзакций выше 35% в течение 30 секунд", 3),
    rule("fraud-stream-stopped", "Поток остановился", "time() - max(fraud_last_processed_timestamp_seconds)", 20, "20s", "Нет транзакций более 20 секунд; условие держится ещё 20 секунд", 1)
]}]}
(ROOT / "grafana/provisioning/alerting/rules.json").write_text(json.dumps(rules, ensure_ascii=False, indent=2) + "\n")
