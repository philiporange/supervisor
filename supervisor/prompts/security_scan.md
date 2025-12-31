# Web Security Scan Prompt

You are performing a security assessment of a web service. Your task is to check for common vulnerabilities and misconfigurations, then return a structured report.

## Target Information
- Service name: {service_name}
- URL: {service_url}
- Port: {port}

## Assessment Tasks

Perform the following checks:

### 1. HTTP Security Headers
Check for presence and correct configuration of:
- Content-Security-Policy
- X-Frame-Options
- X-Content-Type-Options
- Strict-Transport-Security (HSTS)
- X-XSS-Protection
- Referrer-Policy
- Permissions-Policy

### 2. HTTPS/TLS Configuration
- Certificate validity
- TLS version (should be 1.2+)
- Strong cipher suites

### 3. Information Disclosure
- Server header exposure
- Version information in headers
- Error page information leakage
- Directory listing enabled

### 4. Common Vulnerabilities
- Open redirects (test with ?redirect= or ?url= params)
- CORS misconfiguration (check Access-Control-Allow-Origin)
- Cookie security (HttpOnly, Secure, SameSite flags)

### 5. Authentication (if applicable)
- Login endpoint security
- Session management
- Rate limiting presence

## Output Format

You MUST return your findings as a JSON object with this exact structure:

```json
{{
  "service_name": "{service_name}",
  "url": "{service_url}",
  "scan_time": "<ISO timestamp>",
  "summary": {{
    "red": <count>,
    "amber": <count>,
    "green": <count>
  }},
  "findings": [
    {{
      "category": "<category name>",
      "check": "<what was checked>",
      "status": "red|amber|green",
      "detail": "<explanation>",
      "recommendation": "<fix suggestion or null>"
    }}
  ]
}}
```

## Rating Guidelines

- **RED**: Critical security issue that should be fixed immediately
  - Missing HTTPS, exposed credentials, SQL injection, XSS vulnerabilities
  - Severely misconfigured CORS (Access-Control-Allow-Origin: *)
  - Missing authentication on sensitive endpoints

- **AMBER**: Moderate issue or missing best practice
  - Missing security headers (CSP, X-Frame-Options, etc.)
  - Information disclosure (server version, stack traces)
  - Weak but not broken configurations

- **GREEN**: Properly configured / no issues found
  - Security headers present and correct
  - HTTPS with valid certificate
  - No sensitive information exposed

## Important

- Only test the target URL provided - do not scan other hosts
- Use standard HTTP requests only - no aggressive testing
- Focus on passive checks and header analysis
- Return ONLY the JSON output, no other text
