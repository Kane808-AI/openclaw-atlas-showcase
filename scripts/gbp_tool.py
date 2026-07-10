#!/usr/bin/env python3
"""Google Business Profile helper using google_auth.py credentials.

Supports listing account/location info, patching the website URI, and fetching
reviews when Google Business Profile API permissions are available.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlencode

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import AuthorizedSession
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

sys.path.append(str(Path.home() / '.openclaw' / 'scripts'))
from google_auth import (  # type: ignore
    BRAND75_ALL_SCOPES,
    BRAND75_SERVICE_ACCOUNT_FILE,
    BRAND75_SUBJECT,
    get_brand75_credentials,
    get_brand75_gbp_credentials,
    get_personal_credentials,
)

BUSINESS_SCOPE = 'https://www.googleapis.com/auth/business.manage'
REVIEWS_API_ROOT = 'https://mybusiness.googleapis.com/v4'
DEFAULT_LOCATION_QUERY = 'Brand75'

AUTH_MAP = {
    'brand75': get_brand75_credentials,
    'personal': get_personal_credentials,
}


def business_credentials(account: str):
    if account == 'brand75':
        # GBP APIs reject service-account/DWD (quota_limit_value=0).
        # Use user-consent OAuth token minted by auth_brand75_gbp.py.
        return get_brand75_gbp_credentials()
    creds = get_personal_credentials()
    scopes = set(creds.scopes or [])
    if BUSINESS_SCOPE not in scopes:
        raise RuntimeError(
            'Personal OAuth token is missing the required Google Business Profile scope '
            f'({BUSINESS_SCOPE}). Re-auth with that scope before using GBP commands.'
        )
    return creds


def info_service(account: str):
    return build('mybusinessbusinessinformation', 'v1', credentials=business_credentials(account), cache_discovery=False)


def acct_service(account: str):
    return build('mybusinessaccountmanagement', 'v1', credentials=business_credentials(account), cache_discovery=False)


def emit(data):
    print(json.dumps(data, indent=2, sort_keys=True, default=str))


def http_json(account: str, url: str):
    resp = AuthorizedSession(business_credentials(account)).get(url, timeout=120)
    data = {}
    if resp.text:
        try:
            data = resp.json()
        except Exception:
            data = {'raw': resp.text}
    if resp.status_code >= 400:
        raise RuntimeError(
            json.dumps(
                {
                    'status': 'error',
                    'type': 'HttpError',
                    'http_status': resp.status_code,
                    'message': f'GET {url} failed',
                    'body': data,
                },
                sort_keys=True,
            )
        )
    return data


def cmd_accounts(args):
    emit(acct_service(args.account).accounts().list().execute())


def cmd_locations(args):
    emit(info_service(args.account).accounts().locations().list(parent=args.account_name, readMask=args.read_mask, pageSize=args.page_size).execute())


def cmd_update_website(args):
    svc = info_service(args.account)
    body = {'websiteUri': args.website}
    emit(svc.locations().patch(name=args.location_name, updateMask='websiteUri', body=body).execute())


def list_accounts(account: str) -> list[dict]:
    return acct_service(account).accounts().list().execute().get('accounts', [])


def list_locations(account: str, account_name: str, read_mask: str) -> list[dict]:
    return info_service(account).accounts().locations().list(
        parent=account_name,
        readMask=read_mask,
        pageSize=100,
    ).execute().get('locations', [])


def resolve_location(account: str, account_name: str | None, location_name: str | None, query: str):
    read_mask = 'name,title,metadata,websiteUri'
    accounts = [
        {'name': account_name}
    ] if account_name else list_accounts(account)
    if not accounts:
        raise RuntimeError('No Google Business Profile accounts returned for the requested credentials.')

    query_l = query.strip().lower()
    matches: list[tuple[str, dict]] = []
    for acct in accounts:
        acct_name = acct['name']
        locations = list_locations(account, acct_name, read_mask)
        for loc in locations:
            if location_name and loc.get('name') != location_name:
                continue
            haystacks = [
                (loc.get('title') or '').lower(),
                (loc.get('name') or '').lower(),
                (loc.get('websiteUri') or '').lower(),
                json.dumps(loc.get('metadata') or {}).lower(),
            ]
            if location_name or any(query_l in h for h in haystacks):
                matches.append((acct_name, loc))

    if not matches:
        detail = {'query': query, 'accountName': account_name, 'locationName': location_name}
        raise RuntimeError(f'Could not resolve a GBP location: {json.dumps(detail, sort_keys=True)}')
    if len(matches) > 1:
        detail = [
            {'accountName': acct_name, 'locationName': loc.get('name'), 'title': loc.get('title')}
            for acct_name, loc in matches
        ]
        raise RuntimeError(f'Multiple GBP locations matched; rerun with --account-name/--location-name: {json.dumps(detail, sort_keys=True)}')
    return matches[0]


def normalize_review(review: dict) -> dict:
    star = review.get('starRating')
    if isinstance(star, str):
        star_map = {
            'ONE': 1,
            'TWO': 2,
            'THREE': 3,
            'FOUR': 4,
            'FIVE': 5,
            'ONE_STAR': 1,
            'TWO_STAR': 2,
            'THREE_STAR': 3,
            'FOUR_STAR': 4,
            'FIVE_STAR': 5,
        }
        star = star_map.get(star, star)
        if isinstance(star, str) and star.endswith('_STAR'):
            try:
                star = int(star.split('_', 1)[0])
            except Exception:
                pass
    reviewer = review.get('reviewer') or {}
    return {
        'name': review.get('name'),
        'reviewId': (review.get('name') or '').rsplit('/', 1)[-1] if review.get('name') else None,
        'comment': review.get('comment'),
        'starRating': star,
        'createTime': review.get('createTime'),
        'updateTime': review.get('updateTime'),
        'reviewReply': review.get('reviewReply'),
        'reviewer': {
            'displayName': reviewer.get('displayName'),
            'profilePhotoUrl': reviewer.get('profilePhotoUrl'),
        },
    }


def cmd_reviews(args):
    resolved_account_name, location = resolve_location(args.account, args.account_name, args.location_name, args.query)
    location_name = location['name']
    params = {'pageSize': args.page_size, 'orderBy': args.order_by}
    # The Reviews API is still on the legacy v4 surface and requires the
    # account-scoped resource path: accounts/{accountId}/locations/{locationId}.
    # Business Information v1 returns locations/{locationId}, so compose the
    # reviews resource explicitly from the resolved account + location.
    review_parent = f"{resolved_account_name}/{location_name}"
    url = f"{REVIEWS_API_ROOT}/{review_parent}/reviews?{urlencode(params)}"
    payload = http_json(args.account, url)
    reviews = payload.get('reviews', [])
    emit({
        'account': args.account,
        'accountName': resolved_account_name,
        'location': location_name,
        'locationName': location.get('title'),
        'averageRating': location.get('metadata', {}).get('averageRating'),
        'reviewCount': location.get('metadata', {}).get('totalReviewCount'),
        'reviews': [normalize_review(r) for r in reviews],
        'nextPageToken': payload.get('nextPageToken'),
        'api': {
            'endpoint': url,
            'scopeRequired': BUSINESS_SCOPE,
        },
    })


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--account', choices=AUTH_MAP.keys(), default='brand75')
    sub = parser.add_subparsers(dest='command', required=True)

    sub.add_parser('accounts').set_defaults(func=cmd_accounts)

    p = sub.add_parser('locations')
    p.add_argument('--account-name', required=True, help='accounts/123456789')
    p.add_argument('--read-mask', default='name,title,storeCode,websiteUri,phoneNumbers,categories,storefrontAddress,metadata')
    p.add_argument('--page-size', type=int, default=100)
    p.set_defaults(func=cmd_locations)

    p = sub.add_parser('update-website')
    p.add_argument('--location-name', required=True, help='locations/123456789')
    p.add_argument('--website', required=True)
    p.set_defaults(func=cmd_update_website)

    p = sub.add_parser('reviews')
    p.add_argument('--account-name', help='accounts/123456789 (optional if auto-discovery finds Brand75)')
    p.add_argument('--location-name', help='locations/123456789 (optional if auto-discovery finds Brand75)')
    p.add_argument('--query', default=DEFAULT_LOCATION_QUERY, help='Location match string used during auto-discovery (default: Brand75)')
    p.add_argument('--page-size', type=int, default=50)
    p.add_argument('--order-by', default='updateTime desc', help='Reviews list orderBy value')
    p.set_defaults(func=cmd_reviews)

    args = parser.parse_args()
    try:
        args.func(args)
    except HttpError as e:
        body = ''
        try:
            body = e.content.decode()
        except Exception:
            body = str(e)
        print(json.dumps({'status':'error','type':'HttpError','http_status':getattr(getattr(e,'resp',None),'status',None),'message':str(e),'body':body}, indent=2))
        raise SystemExit(1)
    except RefreshError as e:
        detail = str(e)
        hint = None
        if 'unauthorized_client' in detail and BUSINESS_SCOPE in detail:
            hint = f'Brand75 service-account domain-wide delegation is not authorized for {BUSINESS_SCOPE}.'
        elif 'unauthorized_client' in detail:
            hint = f'Brand75 service-account domain-wide delegation is not authorized for {BUSINESS_SCOPE}; add that scope in Google Admin or use a personal OAuth token with GBP access.'
        print(json.dumps({'status':'error','type':'RefreshError','message':detail,'hint':hint}, indent=2))
        raise SystemExit(1)
    except Exception as e:
        print(json.dumps({'status':'error','type':type(e).__name__,'message':str(e)}, indent=2))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
