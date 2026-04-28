#!/bin/bash
exec npx @playwright/mcp@latest --browser chromium "$@"
