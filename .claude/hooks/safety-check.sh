#!/bin/bash
# Safety hook: blocks dangerous commands before execution
# Exit 0 = allow, Exit 2 = block (stderr shown to Claude as feedback)

INPUT=$(cat)
TOOL=$(echo "$INPUT" | jq -r '.tool_name // empty')
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

# Only check Bash commands
if [ "$TOOL" != "Bash" ] && [ -z "$COMMAND" ]; then
  exit 0
fi

# Also check Read tool for sensitive files
if [ "$TOOL" = "Read" ]; then
  FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')
  if echo "$FILE_PATH" | grep -qiE '(\.credentials|\.env$|\.env\.|id_rsa|id_ed25519|private\.key|\.ssh/config|\.netrc|\.pgpass|shadow$|passwd$)'; then
    echo "BLOCKED: Reading sensitive file: $FILE_PATH" >&2
    exit 2
  fi
  exit 0
fi

[ -z "$COMMAND" ] && exit 0

# === DESTRUCTIVE FILE OPERATIONS ===

# Block rm -rf targeting root, /home, or home directories
if echo "$COMMAND" | grep -qE 'rm\s+.*-[a-zA-Z]*r[a-zA-Z]*f|rm\s+.*-[a-zA-Z]*f[a-zA-Z]*r'; then
  # Check if target is a dangerous path
  if echo "$COMMAND" | grep -qE '\s+(/\s|/home\b|~/?\s|/home/[a-z]+/?(\s|$)|/root|/etc|/usr|/var|/boot|/sys|/proc)'; then
    echo "BLOCKED: Recursive forced deletion targeting system/home directory" >&2
    echo "Command: $COMMAND" >&2
    exit 2
  fi
fi

# Block plain rm -rf / or rm -rf ~
if echo "$COMMAND" | grep -qE 'rm\s+-rf\s+(/$|~/?$|/home/?$|/home/\w+/?$)'; then
  echo "BLOCKED: Recursive deletion at root/home level" >&2
  echo "Command: $COMMAND" >&2
  exit 2
fi

# Block chmod/chown -R on system dirs
if echo "$COMMAND" | grep -qE '(chmod|chown)\s+.*-R\s+.*(/$|/home\b|/etc\b|/usr\b|/var\b)'; then
  echo "BLOCKED: Recursive permission change on system directory" >&2
  echo "Command: $COMMAND" >&2
  exit 2
fi

# === SENSITIVE FILE ACCESS ===

# Block reading credential/secret files via shell commands
if echo "$COMMAND" | grep -qiE '(cat|less|more|head|tail|xxd|strings|base64)\s+.*(\.credentials|\.env\b|id_rsa|id_ed25519|private\.key|\.netrc|\.pgpass|shadow|\.aws/credentials|\.ssh/config)'; then
  echo "BLOCKED: Reading sensitive/credential file" >&2
  echo "Command: $COMMAND" >&2
  exit 2
fi

# Block grep/search through secret files
if echo "$COMMAND" | grep -qiE '(grep|rg|ag|ack)\s+.*(\.credentials|\.env\b|id_rsa|private\.key|\.aws/credentials)'; then
  echo "BLOCKED: Searching through sensitive files" >&2
  echo "Command: $COMMAND" >&2
  exit 2
fi

# Block curl/wget posting secrets
if echo "$COMMAND" | grep -qiE '(curl|wget)\s+.*(-d|--data)\s+.*(password|secret|token|api.key|credential)'; then
  echo "BLOCKED: Sending sensitive data via HTTP" >&2
  echo "Command: $COMMAND" >&2
  exit 2
fi

# === GIT SAFETY ===

# Block force push to main/master
if echo "$COMMAND" | grep -qE 'git\s+push\s+.*(-f|--force)'; then
  if echo "$COMMAND" | grep -qE '(main|master)'; then
    echo "BLOCKED: Force push to main/master" >&2
    echo "Command: $COMMAND" >&2
    exit 2
  fi
fi

# Block git reset --hard on main
if echo "$COMMAND" | grep -qE 'git\s+reset\s+--hard'; then
  echo "BLOCKED: git reset --hard (destructive, may lose work)" >&2
  echo "Command: $COMMAND" >&2
  exit 2
fi

# Block git clean -f (deletes untracked files)
if echo "$COMMAND" | grep -qE 'git\s+clean\s+.*-[a-zA-Z]*f'; then
  echo "BLOCKED: git clean -f (deletes untracked files)" >&2
  echo "Command: $COMMAND" >&2
  exit 2
fi

# === SYSTEM SAFETY ===

# Block killing system-critical processes
if echo "$COMMAND" | grep -qiE '(kill|killall|pkill)\s+.*(init|systemd|sshd|dockerd|containerd|kernel)'; then
  echo "BLOCKED: Killing critical system process" >&2
  echo "Command: $COMMAND" >&2
  exit 2
fi

# Block dd to block devices
if echo "$COMMAND" | grep -qE 'dd\s+.*of=/dev/(sd|nvme|vd|hd|loop)'; then
  echo "BLOCKED: Writing directly to block device" >&2
  echo "Command: $COMMAND" >&2
  exit 2
fi

# Block mkfs on devices
if echo "$COMMAND" | grep -qE 'mkfs'; then
  echo "BLOCKED: Filesystem formatting not allowed" >&2
  echo "Command: $COMMAND" >&2
  exit 2
fi

# All checks passed
exit 0
