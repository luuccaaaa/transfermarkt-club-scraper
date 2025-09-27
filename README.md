# Transfermarkt Workflow System

Football club data scraper with console-style web interface for generating Excel workbooks.

## Quick Start

**Prerequisites**: Docker and Docker Compose

1. **Start services**:
   ```bash
   docker-compose up -d
   ```

2. **Access web interface**: http://localhost:3000

## Proxy Configuration

For reliable data fetching, configure proxies in `config/proxies.txt`:

```
http://proxy1:port
http://proxy2:port
socks5://proxy3:port
```

The system will automatically cycle through proxies to avoid rate limiting.

## Docker Setup

Three services running on:
- **Frontend** (port 3000): Web interface
- **Workflow API** (port 8080): Job orchestration 
- **Transfermarkt API** (port 8000): Data scraping

**Rebuild after changes**:
```bash
docker-compose down
docker-compose up -d --build
```

## Troubleshooting

**403 Errors**: Check proxy configuration in `config/proxies.txt`

**Container issues**: View logs with `docker-compose logs [service_name]`

**Build errors**: Use `docker-compose build --no-cache`
