"""What the endpoints do when Nominatim or OSRM does not answer properly.

Every test here is a shape of response that used to reach the browser as a 500,
because the code called .json() on whatever came back without looking at it
first. The production failure was the second one: Nominatim served a block page
to Render's shared datacenter IP, .json() met HTML, and JSONDecodeError went
straight through FastAPI.
"""

import httpx
import pytest

import config

BLOCK_PAGE = "\n<html><body>Access blocked</body></html>"

ROUTE_PARAMS = {
    "start_lat": 23.8103,
    "start_lng": 90.4125,
    "end_lat": 23.7806,
    "end_lng": 90.4193,
}


def reverse_geocode(client):
    return client.get("/reverse-geocode", params={"lat": 23.8103, "lng": 90.4125})


def search(client):
    return client.get("/search", params={"query": "Gulshan"})


def route(client):
    return client.get("/route", params=ROUTE_PARAMS)


@pytest.mark.parametrize("call", [reverse_geocode, search, route])
def test_a_non_200_never_gets_parsed(client, upstream, call):
    upstream.replies(status_code=403, text=BLOCK_PAGE)

    assert call(client).status_code == 502


@pytest.mark.parametrize("call", [reverse_geocode, search, route])
def test_a_200_that_is_not_json_is_a_502_not_a_500(client, upstream, call):
    """The production bug, one per call site.

    A block page is served with 200 as often as not, so the status check alone
    does not catch it — the parse has to be guarded too.
    """
    upstream.replies(status_code=200, text=BLOCK_PAGE)

    assert call(client).status_code == 502


@pytest.mark.parametrize("call", [reverse_geocode, search, route])
def test_no_response_at_all_is_a_502(client, upstream, call):
    """Timeout, DNS failure, connection reset — nothing to check a status on."""
    upstream.raises(httpx.ConnectTimeout("timed out"))

    assert call(client).status_code == 502


@pytest.mark.parametrize("call", [reverse_geocode, search, route])
def test_the_upstream_body_is_not_echoed_to_the_client(client, upstream, call):
    """An error page can name our egress IP or quote the query back."""
    upstream.replies(status_code=403, text="blocked: 216.24.57.1 exceeded quota")

    body = call(client).text

    assert "216.24.57.1" not in body
    assert "exceeded quota" not in body


@pytest.mark.parametrize("call", [reverse_geocode, search, route])
def test_every_outbound_request_identifies_the_application(client, upstream, call):
    """Nominatim's policy asks for a contactable User-Agent; OSRM had none."""
    upstream.replies(status_code=200, json=[])

    call(client)

    assert upstream.requests
    assert upstream.requests[0].headers["user-agent"] == config.USER_AGENT
    assert "github.com/riazur-13/dhaka-route-app" in config.USER_AGENT


@pytest.mark.parametrize("call", [reverse_geocode, search, route])
def test_every_outbound_request_carries_an_explicit_timeout(client, upstream, call):
    upstream.replies(status_code=200, json=[])

    call(client)

    timeout = upstream.requests[0].extensions["timeout"]
    assert timeout["connect"] == 5.0
    assert timeout["read"] == 10.0


def test_search_rejects_an_error_object_where_a_list_belongs(client, upstream):
    """Iterating Nominatim's error object yields its keys, then TypeErrors."""
    upstream.replies(status_code=200, json={"error": "Unable to geocode"})

    assert search(client).status_code == 502


def test_route_survives_a_json_body_without_the_documented_shape(client, upstream):
    """data["code"] on an unexpected object was a KeyError, so a 500."""
    upstream.replies(status_code=200, json={"unexpected": True})

    assert route(client).status_code == 400


def test_route_survives_ok_with_no_routes(client, upstream):
    upstream.replies(status_code=200, json={"code": "Ok", "routes": []})

    assert route(client).status_code == 400


def test_a_working_route_still_works(client, upstream):
    upstream.replies(
        status_code=200,
        json={
            "code": "Ok",
            "routes": [
                {
                    "geometry": {"coordinates": [[90.4125, 23.8103], [90.4193, 23.7806]]},
                    "distance": 4200.0,
                    "duration": 3360.0,
                }
            ],
        },
    )

    response = route(client)

    assert response.status_code == 200
    assert response.json()["distance"] == 4200.0


def test_a_working_search_still_works(client, upstream):
    upstream.replies(
        status_code=200,
        json=[
            {
                "display_name": "Gulshan 1, Gulshan, Dhaka, Bangladesh",
                "lat": "23.7806",
                "lon": "90.4193",
            }
        ],
    )

    response = search(client)

    assert response.status_code == 200
    assert response.json()["results"][0]["name"] == "Gulshan 1, Gulshan, Dhaka"
