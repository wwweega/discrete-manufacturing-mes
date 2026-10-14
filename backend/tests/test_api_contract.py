"""API 契约测试：统一响应结构、参数校验、RBAC 在 HTTP 层的表现。"""

from __future__ import annotations

import pytest


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_health_endpoint_returns_unified_envelope(api_client):
    client, *_ = api_client
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["db_engine"] == "sqlite"


def test_login_response_contains_three_accounts_permissions(api_client):
    client, *_ = api_client
    body = client.post("/api/v1/auth/login",
                       json={"username": "worker", "password": "mes@2026"}).json()
    assert body["code"] == 0
    assert body["data"]["roles"] == ["operator"]
    assert "order:report" in body["data"]["permissions"]
    assert "order:cancel" not in body["data"]["permissions"]


def test_validation_error_returns_readable_message(api_client):
    client, admin_token, *_ = api_client
    resp = client.post("/api/v1/auth/login", json={"username": "", "password": ""})
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == 4220
    assert "参数校验失败" in body["msg"]
    assert body["data"]["errors"], "必须给出字段级错误信息"


def test_business_error_uses_unified_envelope(api_client):
    client, admin_token, *_ = api_client
    resp = client.get("/api/v1/orders/999999", headers=_auth(admin_token))
    assert resp.status_code == 404
    body = resp.json()
    assert body["code"] != 0
    assert "工单不存在" in body["msg"]


def test_missing_token_is_rejected(api_client):
    client, *_ = api_client
    resp = client.get("/api/v1/orders")
    assert resp.status_code == 401
    assert resp.json()["code"] != 0


def test_operator_cannot_release_order_but_can_report(api_client, running_order):
    client, admin_token, leader_token, worker_token = api_client
    order, operation = running_order

    # 操作工没有下达权限
    resp = client.post(f"/api/v1/orders/{order.id}/transition",
                       json={"target_status": "COMPLETED"},
                       headers=_auth(worker_token))
    assert resp.status_code == 403
    assert "无操作权限" in resp.json()["msg"]

    # 操作工可以报工
    resp = client.post(f"/api/v1/orders/{order.id}/report",
                       json={"operation_id": operation.id, "qty_good": 10},
                       headers={**_auth(worker_token), "Idempotency-Key": "api-wo-1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["duplicated"] is False
    assert body["data"]["qty_good"] == 10


def test_duplicate_report_via_http_returns_same_report_no(api_client, running_order):
    client, admin_token, _, worker_token = api_client
    order, operation = running_order

    headers = {**_auth(worker_token), "Idempotency-Key": "api-dup-001"}
    payload = {"operation_id": operation.id, "qty_good": 5}

    first = client.post(f"/api/v1/orders/{order.id}/report",
                        json=payload, headers=headers).json()
    second = client.post(f"/api/v1/orders/{order.id}/report",
                         json=payload, headers=headers).json()

    assert first["data"]["report_no"] == second["data"]["report_no"]
    assert second["data"]["duplicated"] is True
    assert "重复提交" in second["data"]["message"]


def test_swagger_json_is_generated(api_client):
    client, *_ = api_client
    body = client.get("/openapi.json").json()
    assert body["info"]["title"]
    paths = body["paths"]
    assert "/api/v1/orders/{order_id}/report" in paths
    assert "/api/v1/reports/{code}" in paths
    assert "/api/v1/dashboard/stream" in paths


def test_reports_endpoint_requires_permission(api_client, running_order):
    client, admin_token, leader_token, worker_token = api_client
    resp = client.get("/api/v1/reports/work_order_progress", headers=_auth(worker_token))
    assert resp.status_code == 403          # 操作工无报表权限

    resp = client.get("/api/v1/reports/work_order_progress", headers=_auth(leader_token))
    assert resp.status_code == 200
    assert resp.json()["code"] == 0
