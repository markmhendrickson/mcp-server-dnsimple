#!/usr/bin/env python3
"""
MCP Server for DNSimple API Interactions

Provides tools for domain management, DNS configuration, pricing queries, and domain transfers.
"""

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# DNSimple API configuration
DNSIMPLE_API_BASE = "https://api.dnsimple.com/v2"

# Configuration directory (portable, uses user's home directory)
CONFIG_DIR = Path.home() / ".config" / "dnsimple-mcp"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
ENV_FILE = CONFIG_DIR / ".env"

# Optional: Try to import 1Password credential utility if available
# This allows the MCP server to work standalone or with 1Password integration
HAS_CREDENTIALS_MODULE = False
try:
    # Try importing from common locations (for backward compatibility)
    # First try parent repo structure (if running from this repo)
    server_dir = Path(__file__).parent
    possible_paths = [
        server_dir.parent.parent.parent,  # execution/mcp-servers/dnsimple -> execution -> personal
        server_dir.parent.parent,  # mcp-servers/dnsimple -> mcp-servers -> execution
    ]
    
    for parent_path in possible_paths:
        credentials_path = parent_path / "execution" / "scripts" / "credentials.py"
        if credentials_path.exists():
            sys.path.insert(0, str(parent_path))
            try:
                from execution.scripts.credentials import get_credential, get_credential_by_domain
                HAS_CREDENTIALS_MODULE = True
                break
            except ImportError:
                continue
except Exception:
    pass

# Initialize MCP server
app = Server("dnsimple")


def load_token_from_env() -> Optional[str]:
    """Load DNSimple API token from environment variable or .env file."""
    # First check environment variable (highest priority)
    token = os.getenv("DNSIMPLE_API_TOKEN")
    if token:
        return token
    
    # Then check .env file in config directory
    if not ENV_FILE.exists():
        return None
    
    try:
        with open(ENV_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith("DNSIMPLE_API_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                    # Remove quotes if present
                    if token.startswith('"') and token.endswith('"'):
                        token = token[1:-1]
                    elif token.startswith("'") and token.endswith("'"):
                        token = token[1:-1]
                    return token
    except Exception:
        pass
    
    return None


def get_dnsimple_token_from_1password() -> Optional[str]:
    """Get DNSimple API token from 1Password."""
    if not HAS_CREDENTIALS_MODULE:
        return None
    
    try:
        field_names = ["access token", "api_token", "token", "api token"]
        for field_name in field_names:
            try:
                token = get_credential("DNSimple", field=field_name)
                if token:
                    return token
            except (ValueError, KeyError):
                continue
        
        for field_name in field_names:
            try:
                token = get_credential_by_domain("dnsimple.com", field=field_name)
                if token:
                    return token
            except (ValueError, KeyError):
                continue
        
        return None
    except Exception:
        return None


def get_dnsimple_token() -> Optional[str]:
    """Get DNSimple API token from environment variable, .env file, or 1Password."""
    # Priority: environment variable > .env file > 1Password
    token = load_token_from_env()
    if token:
        return token
    
    token = get_dnsimple_token_from_1password()
    return token


def get_account_id(api_token: str) -> str:
    """Get DNSimple account ID."""
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Accept": "application/json",
    }
    
    response = requests.get(f"{DNSIMPLE_API_BASE}/whoami", headers=headers)
    
    if response.status_code != 200:
        response.raise_for_status()
    
    data = response.json()
    
    if not data or "data" not in data:
        raise ValueError("Invalid API response: missing 'data' key")
    
    account = data["data"].get("account")
    if account and account.get("id"):
        return str(account["id"])
    
    # If account is null, list accounts and use the first one
    response = requests.get(f"{DNSIMPLE_API_BASE}/accounts", headers=headers)
    response.raise_for_status()
    
    accounts_data = response.json()
    if not accounts_data or "data" not in accounts_data or not accounts_data["data"]:
        raise ValueError("No accounts found. You may need to create an account first.")
    
    account_id = accounts_data["data"][0]["id"]
    return str(account_id)


def list_domains(api_token: str, account_id: str) -> List[Dict[str, Any]]:
    """List all domains in the account."""
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Accept": "application/json",
    }
    
    domains = []
    page = 1
    
    while True:
        response = requests.get(
            f"{DNSIMPLE_API_BASE}/{account_id}/domains",
            headers=headers,
            params={"page": page, "per_page": 100}
        )
        response.raise_for_status()
        
        data = response.json()
        domains.extend(data.get("data", []))
        
        pagination = data.get("pagination", {})
        if pagination.get("current_page", 0) >= pagination.get("total_pages", 1):
            break
        
        page += 1
    
    return domains


@app.list_tools()
async def list_tools() -> List[Tool]:
    """List available MCP tools."""
    return [
        Tool(
            name="get_domain_costs",
            description="Get pricing information for domains. Returns registration and renewal costs.",
            inputSchema={
                "type": "object",
                "properties": {
                    "domain_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of domain names to get pricing for. If empty, returns pricing for all domains in account.",
                    },
                },
            },
        ),
        Tool(
            name="get_renewal_costs",
            description="Get renewal costs for domains. Returns total annual renewal cost and per-domain breakdown.",
            inputSchema={
                "type": "object",
                "properties": {
                    "domain_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of domain names to get renewal costs for. If empty, returns costs for all domains in account.",
                    },
                },
            },
        ),
        Tool(
            name="configure_dns_record",
            description="Create or update a DNS record. If a record with the same name and type exists, it will be updated.",
            inputSchema={
                "type": "object",
                "properties": {
                    "domain_name": {
                        "type": "string",
                        "description": "Domain name (e.g., 'example.com')",
                    },
                    "name": {
                        "type": "string",
                        "description": "Record name (e.g., 'www' or '@' for root domain)",
                    },
                    "type": {
                        "type": "string",
                        "enum": ["A", "AAAA", "CNAME", "MX", "TXT", "NS", "SRV", "ALIAS"],
                        "description": "DNS record type",
                    },
                    "content": {
                        "type": "string",
                        "description": "Record content (IP address for A/AAAA, hostname for CNAME, etc.)",
                    },
                    "ttl": {
                        "type": "integer",
                        "description": "TTL in seconds (default: 3600)",
                        "default": 3600,
                    },
                    "priority": {
                        "type": "integer",
                        "description": "Priority for MX records (optional)",
                    },
                },
                "required": ["domain_name", "name", "type", "content"],
            },
        ),
        Tool(
            name="list_dns_records",
            description="List DNS records for a domain.",
            inputSchema={
                "type": "object",
                "properties": {
                    "domain_name": {
                        "type": "string",
                        "description": "Domain name (e.g., 'example.com')",
                    },
                    "name": {
                        "type": "string",
                        "description": "Filter by record name (optional)",
                    },
                    "type": {
                        "type": "string",
                        "description": "Filter by record type (optional)",
                    },
                },
                "required": ["domain_name"],
            },
        ),
        Tool(
            name="delete_dns_record",
            description="Delete a DNS record by ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "domain_name": {
                        "type": "string",
                        "description": "Domain name (e.g., 'example.com')",
                    },
                    "record_id": {
                        "type": "string",
                        "description": "DNS record ID to delete",
                    },
                },
                "required": ["domain_name", "record_id"],
            },
        ),
        Tool(
            name="disable_autorenew",
            description="Disable auto-renewal for one or more domains.",
            inputSchema={
                "type": "object",
                "properties": {
                    "domain_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of domain names to disable auto-renewal for",
                    },
                },
                "required": ["domain_names"],
            },
        ),
        Tool(
            name="transfer_domain",
            description="Initiate a domain transfer to DNSimple. Requires authorization code from current registrar.",
            inputSchema={
                "type": "object",
                "properties": {
                    "domain_name": {
                        "type": "string",
                        "description": "Domain name to transfer",
                    },
                    "auth_code": {
                        "type": "string",
                        "description": "Authorization code (EPP code) from current registrar",
                    },
                    "registrant_id": {
                        "type": "string",
                        "description": "Registrant ID (optional, uses account default if not provided)",
                    },
                },
                "required": ["domain_name", "auth_code"],
            },
        ),
        Tool(
            name="list_domains",
            description="List all domains in the DNSimple account.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="get_whois_privacy",
            description="Get whois privacy status for a domain.",
            inputSchema={
                "type": "object",
                "properties": {
                    "domain_name": {
                        "type": "string",
                        "description": "Domain name (e.g., 'example.com')",
                    },
                },
                "required": ["domain_name"],
            },
        ),
        Tool(
            name="enable_whois_privacy",
            description="Enable whois privacy (domain privacy) for a domain. This will purchase and enable whois privacy if not already enabled.",
            inputSchema={
                "type": "object",
                "properties": {
                    "domain_name": {
                        "type": "string",
                        "description": "Domain name (e.g., 'example.com')",
                    },
                },
                "required": ["domain_name"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle tool calls."""
    api_token = get_dnsimple_token()
    
    if not api_token:
        return [TextContent(
            type="text",
            text=json.dumps({
                "error": "DNSimple API token not found. Set DNSIMPLE_API_TOKEN environment variable or configure 1Password credentials.",
            }, indent=2)
        )]
    
    try:
        account_id = get_account_id(api_token)
    except Exception as e:
        return [TextContent(
            type="text",
            text=json.dumps({
                "error": f"Failed to get account ID: {str(e)}",
            }, indent=2)
        )]
    
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Accept": "application/json",
    }
    
    if name == "get_domain_costs":
        domain_names = arguments.get("domain_names", [])
        
        if not domain_names:
            # Get all domains
            try:
                domains = list_domains(api_token, account_id)
                domain_names = [d["name"] for d in domains]
            except Exception as e:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "error": f"Failed to list domains: {str(e)}",
                    }, indent=2)
                )]
        
        results = []
        for domain_name in domain_names:
            tld = domain_name.split(".")[-1]
            
            # Get TLD pricing
            try:
                response = requests.get(
                    f"{DNSIMPLE_API_BASE}/{account_id}/registrar/tlds/{tld}/prices",
                    headers=headers
                )
                prices_data = []
                if response.status_code == 200:
                    result = response.json()
                    prices_data = result.get("data", [])
            except Exception as e:
                prices_data = []
            
            # Try to get domain registration info
            domain_data = None
            try:
                response = requests.get(
                    f"{DNSIMPLE_API_BASE}/{account_id}/registrar/domains/{domain_name}",
                    headers=headers
                )
                if response.status_code == 200:
                    domain_data = response.json().get("data")
            except:
                pass
            
            results.append({
                "domain": domain_name,
                "domain_info": domain_data,
                "prices": prices_data,
            })
        
        return [TextContent(
            type="text",
            text=json.dumps({
                "account_id": account_id,
                "domains": results,
            }, indent=2, default=str)
        )]
    
    elif name == "get_renewal_costs":
        domain_names = arguments.get("domain_names", [])
        
        if not domain_names:
            try:
                domains = list_domains(api_token, account_id)
                domain_names = [d["name"] for d in domains]
            except Exception as e:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "error": f"Failed to list domains: {str(e)}",
                    }, indent=2)
                )]
        
        total_renewal_cost = 0
        domain_details = []
        
        for domain_name in domain_names:
            tld = domain_name.split(".")[-1]
            
            # Get domain info
            try:
                response = requests.get(
                    f"{DNSIMPLE_API_BASE}/{account_id}/registrar/domains/{domain_name}",
                    headers=headers
                )
                domain_data = response.json().get("data") if response.status_code == 200 else None
            except:
                domain_data = None
            
            # Get renewal price
            renewal_price = None
            try:
                response = requests.get(
                    f"{DNSIMPLE_API_BASE}/{account_id}/registrar/tlds/{tld}/prices",
                    headers=headers
                )
                if response.status_code == 200:
                    prices = response.json().get("data", [])
                    renewal_price = next((p for p in prices if p.get("operation") == "renew"), None)
            except:
                pass
            
            if renewal_price:
                amount = float(renewal_price.get("price", 0))
                currency = renewal_price.get("currency", "USD")
                total_renewal_cost += amount
                
                domain_details.append({
                    "domain": domain_name,
                    "expires_at": domain_data.get("expires_at") if domain_data else None,
                    "auto_renew": domain_data.get("auto_renew", False) if domain_data else None,
                    "renewal_price": amount,
                    "currency": currency,
                })
            else:
                domain_details.append({
                    "domain": domain_name,
                    "expires_at": domain_data.get("expires_at") if domain_data else None,
                    "auto_renew": domain_data.get("auto_renew", False) if domain_data else None,
                    "renewal_price": None,
                    "currency": None,
                })
        
        return [TextContent(
            type="text",
            text=json.dumps({
                "account_id": account_id,
                "total_domains": len(domain_names),
                "total_annual_renewal_cost": total_renewal_cost,
                "domains": domain_details,
            }, indent=2, default=str)
        )]
    
    elif name == "configure_dns_record":
        domain_name = arguments["domain_name"]
        record_name = arguments["name"]
        record_type = arguments["type"]
        content = arguments["content"]
        ttl = arguments.get("ttl", 3600)
        priority = arguments.get("priority")
        
        # First, check if record exists
        try:
            response = requests.get(
                f"{DNSIMPLE_API_BASE}/{account_id}/zones/{domain_name}/records",
                headers=headers,
                params={"name": record_name, "type": record_type}
            )
            response.raise_for_status()
            existing_records = response.json().get("data", [])
        except:
            existing_records = []
        
        # Prepare record data
        record_data = {
            "name": record_name,
            "type": record_type,
            "content": content,
            "ttl": ttl,
        }
        if priority is not None:
            record_data["priority"] = priority
        
        if existing_records:
            # Update existing record
            record_id = existing_records[0]["id"]
            response = requests.patch(
                f"{DNSIMPLE_API_BASE}/{account_id}/zones/{domain_name}/records/{record_id}",
                headers={**headers, "Content-Type": "application/json"},
                json=record_data
            )
            action = "updated"
        else:
            # Create new record
            response = requests.post(
                f"{DNSIMPLE_API_BASE}/{account_id}/zones/{domain_name}/records",
                headers={**headers, "Content-Type": "application/json"},
                json=record_data
            )
            action = "created"
        
        if response.status_code in [200, 201]:
            return [TextContent(
                type="text",
                text=json.dumps({
                    "success": True,
                    "action": action,
                    "record": response.json().get("data"),
                }, indent=2, default=str)
            )]
        else:
            return [TextContent(
                type="text",
                text=json.dumps({
                    "error": f"Failed to {action} DNS record: {response.status_code}",
                    "response": response.text,
                }, indent=2)
            )]
    
    elif name == "list_dns_records":
        domain_name = arguments["domain_name"]
        filter_name = arguments.get("name")
        filter_type = arguments.get("type")
        
        records = []
        page = 1
        
        while True:
            params = {"page": page, "per_page": 100}
            if filter_name:
                params["name"] = filter_name
            if filter_type:
                params["type"] = filter_type
            
            response = requests.get(
                f"{DNSIMPLE_API_BASE}/{account_id}/zones/{domain_name}/records",
                headers=headers,
                params=params
            )
            response.raise_for_status()
            
            data = response.json()
            records.extend(data.get("data", []))
            
            pagination = data.get("pagination", {})
            if pagination.get("current_page", 0) >= pagination.get("total_pages", 1):
                break
            
            page += 1
        
        return [TextContent(
            type="text",
            text=json.dumps({
                "domain": domain_name,
                "count": len(records),
                "records": records,
            }, indent=2, default=str)
        )]
    
    elif name == "delete_dns_record":
        domain_name = arguments["domain_name"]
        record_id = arguments["record_id"]
        
        response = requests.delete(
            f"{DNSIMPLE_API_BASE}/{account_id}/zones/{domain_name}/records/{record_id}",
            headers=headers
        )
        
        if response.status_code in [200, 204]:
            return [TextContent(
                type="text",
                text=json.dumps({
                    "success": True,
                    "message": f"DNS record {record_id} deleted",
                }, indent=2)
            )]
        else:
            return [TextContent(
                type="text",
                text=json.dumps({
                    "error": f"Failed to delete DNS record: {response.status_code}",
                    "response": response.text,
                }, indent=2)
            )]
    
    elif name == "disable_autorenew":
        domain_names = arguments["domain_names"]
        results = []
        
        for domain_name in domain_names:
            data = {"auto_renew": False}
            response = requests.patch(
                f"{DNSIMPLE_API_BASE}/{account_id}/registrar/domains/{domain_name}",
                headers={**headers, "Content-Type": "application/json"},
                json=data
            )
            
            if response.status_code == 200:
                results.append({
                    "domain": domain_name,
                    "status": "disabled",
                    "error": None,
                })
            else:
                results.append({
                    "domain": domain_name,
                    "status": "failed",
                    "error": f"API Error {response.status_code}: {response.text}",
                })
        
        return [TextContent(
            type="text",
            text=json.dumps({
                "results": results,
            }, indent=2, default=str)
        )]
    
    elif name == "transfer_domain":
        domain_name = arguments["domain_name"]
        auth_code = arguments["auth_code"]
        registrant_id = arguments.get("registrant_id")
        
        data = {
            "auth_code": auth_code,
        }
        if registrant_id:
            data["registrant_id"] = registrant_id
        
        response = requests.post(
            f"{DNSIMPLE_API_BASE}/{account_id}/registrar/domains/{domain_name}/transfers",
            headers={**headers, "Content-Type": "application/json"},
            json=data
        )
        
        if response.status_code in [200, 201]:
            return [TextContent(
                type="text",
                text=json.dumps({
                    "success": True,
                    "transfer": response.json().get("data"),
                }, indent=2, default=str)
            )]
        else:
            error_text = response.text
            try:
                error_json = response.json()
                error_message = error_json.get("message", error_text)
            except:
                error_message = error_text
            
            return [TextContent(
                type="text",
                text=json.dumps({
                    "error": f"Failed to initiate transfer: {response.status_code}",
                    "message": error_message,
                }, indent=2)
            )]
    
    elif name == "list_domains":
        try:
            domains = list_domains(api_token, account_id)
            return [TextContent(
                type="text",
                text=json.dumps({
                    "account_id": account_id,
                    "count": len(domains),
                    "domains": domains,
                }, indent=2, default=str)
            )]
        except Exception as e:
            return [TextContent(
                type="text",
                text=json.dumps({
                    "error": f"Failed to list domains: {str(e)}",
                }, indent=2)
            )]
    
    elif name == "get_whois_privacy":
        domain_name = arguments["domain_name"]
        
        try:
            response = requests.get(
                f"{DNSIMPLE_API_BASE}/{account_id}/registrar/domains/{domain_name}/whois_privacy",
                headers=headers
            )
            
            if response.status_code == 200:
                whois_data = response.json().get("data", {})
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "domain": domain_name,
                        "whois_privacy": whois_data,
                        "enabled": whois_data.get("enabled", False),
                        "expires_on": whois_data.get("expires_on"),
                    }, indent=2, default=str)
                )]
            elif response.status_code == 404:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "domain": domain_name,
                        "enabled": False,
                        "message": "Whois privacy not purchased or not available for this domain",
                    }, indent=2)
                )]
            else:
                error_text = response.text
                try:
                    error_json = response.json()
                    error_message = error_json.get("message", error_text)
                except:
                    error_message = error_text
                
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "error": f"Failed to get whois privacy status: {response.status_code}",
                        "message": error_message,
                    }, indent=2)
                )]
        except Exception as e:
            return [TextContent(
                type="text",
                text=json.dumps({
                    "error": f"Failed to get whois privacy: {str(e)}",
                }, indent=2)
            )]
    
    elif name == "enable_whois_privacy":
        domain_name = arguments["domain_name"]
        
        try:
            # First check current status
            response = requests.get(
                f"{DNSIMPLE_API_BASE}/{account_id}/registrar/domains/{domain_name}/whois_privacy",
                headers=headers
            )
            
            if response.status_code == 200:
                whois_data = response.json().get("data", {})
                if whois_data.get("enabled", False):
                    return [TextContent(
                        type="text",
                        text=json.dumps({
                            "domain": domain_name,
                            "status": "already_enabled",
                            "message": "Whois privacy is already enabled for this domain",
                            "whois_privacy": whois_data,
                        }, indent=2, default=str)
                    )]
            
            # Enable/purchase whois privacy
            response = requests.put(
                f"{DNSIMPLE_API_BASE}/{account_id}/registrar/domains/{domain_name}/whois_privacy",
                headers={**headers, "Content-Type": "application/json"}
            )
            
            if response.status_code in [200, 201]:
                whois_data = response.json().get("data", {})
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "success": True,
                        "domain": domain_name,
                        "status": "enabled",
                        "message": "Whois privacy has been enabled for this domain",
                        "whois_privacy": whois_data,
                    }, indent=2, default=str)
                )]
            else:
                error_text = response.text
                try:
                    error_json = response.json()
                    error_message = error_json.get("message", error_text)
                except:
                    error_message = error_text
                
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "error": f"Failed to enable whois privacy: {response.status_code}",
                        "message": error_message,
                    }, indent=2)
                )]
        except Exception as e:
            return [TextContent(
                type="text",
                text=json.dumps({
                    "error": f"Failed to enable whois privacy: {str(e)}",
                }, indent=2)
            )]
    
    else:
        return [TextContent(
            type="text",
            text=json.dumps({
                "error": f"Unknown tool: {name}",
            }, indent=2)
        )]


async def main():
    """Main entry point."""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())

