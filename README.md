# DNSimple MCP Server

MCP server for DNSimple API interactions, providing tools for domain management, DNS configuration, pricing queries, and domain transfers.

## Features

- **Domain Management**: List domains, get pricing, check renewal costs
- **DNS Configuration**: Create, update, list, and delete DNS records
- **Auto-Renewal Control**: Disable auto-renewal for domains
- **Domain Transfers**: Initiate domain transfers to DNSimple

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Configure authentication:
   - Option 1: Set `DNSIMPLE_API_TOKEN` environment variable
   - Option 2: Configure 1Password credentials (item titled "DNSimple" or with URL "dnsimple.com", field: "access token", "api_token", or "token")

3. Get your DNSimple API token from: https://dnsimple.com/user

## Available Tools

- `get_domain_costs` - Get pricing information for domains
- `get_renewal_costs` - Get renewal costs for domains
- `configure_dns_record` - Create or update DNS records
- `list_dns_records` - List DNS records for a domain
- `delete_dns_record` - Delete a DNS record
- `disable_autorenew` - Disable auto-renewal for domains
- `transfer_domain` - Initiate domain transfer to DNSimple
- `list_domains` - List all domains in account

## Usage

The server follows the MCP protocol and can be used with any MCP-compatible client.

## Authentication

The server supports two authentication methods:
1. Environment variable: `DNSIMPLE_API_TOKEN`
2. 1Password integration (if credentials module is available)

The token is automatically cached to `.env` file for future use.

