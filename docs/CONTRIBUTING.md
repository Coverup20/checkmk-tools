# Contributing to CheckMK Tools

Thank you for your interest in contributing to the CheckMK Tools repository! This document provides guidelines for contributing.

## How to Contribute

### Reporting Bugs

If you find a bug, please create an issue with:
- Clear description of the problem
- Steps to reproduce
- Expected behavior
- Actual behavior
- System information (OS, CheckMK version, etc.)
- Relevant log output or error messages

### Suggesting Enhancements

Enhancement suggestions are welcome! Please create an issue with:
- Clear description of the enhancement
- Use case and benefits
- Possible implementation approach
- Any relevant examples

### Contributing Code

1. **Fork the repository**
   ```bash
   # Fork on GitHub, then clone your fork
   git clone https://github.com/YOUR_USERNAME/checkmk-tools.git
   cd checkmk-tools
   ```

2. **Create a feature branch**
   ```bash
   git checkout -b feature/your-feature-name
   ```

3. **Make your changes**
   - Follow the coding standards (see below)
   - Test your changes thoroughly
   - Update documentation as needed

4. **Commit your changes**
   ```bash
   git add .
   git commit -m "Add: Brief description of your changes"
   ```

5. **Push to your fork**
   ```bash
   git push origin feature/your-feature-name
   ```

6. **Create a Pull Request**
   - Go to the original repository on GitHub
   - Click "New Pull Request"
   - Select your fork and branch
   - Provide a clear description of changes

## Coding Standards

### Shell Scripts (Bash)

- Use `#!/usr/bin/env bash` shebang
- Include `set -euo pipefail` for safety
- Use meaningful variable names (UPPERCASE for constants)
- Comment complex logic
- Quote variables: `"$VAR"` not `$VAR`
- Use `[[ ]]` instead of `[ ]` for tests
- Check command existence: `command -v cmd >/dev/null 2>&1`

**Example:**
```bash
#!/usr/bin/env bash
set -euo pipefail

# Constants
BACKUP_DIR="/var/backups"
RETENTION_DAYS=30

# Check if directory exists
if [[ ! -d "$BACKUP_DIR" ]]; then
    echo "Error: Backup directory not found"
    exit 1
fi

# Function with clear purpose
cleanup_old_backups() {
    local dir="$1"
    find "$dir" -type f -mtime +"$RETENTION_DAYS" -delete
}

cleanup_old_backups "$BACKUP_DIR"
```

### PowerShell Scripts

- Use proper verb-noun naming conventions
- Set `$ErrorActionPreference = "SilentlyContinue"` when appropriate
- Use try-catch for error handling
- Comment complex logic
- Use proper indentation (4 spaces)

**Example:**
```powershell
# Set error handling
$ErrorActionPreference = "SilentlyContinue"

# Function with clear purpose
function Get-SystemInfo {
    try {
        $OS = Get-CimInstance Win32_OperatingSystem
        Write-Host "OS: $($OS.Caption)"
    } catch {
        Write-Host "Error: Unable to get system info"
    }
}

Get-SystemInfo
```

### CheckMK Agent Plugins

Agent plugins must follow CheckMK's output format:

```bash
#!/usr/bin/env bash
set -e

# Output section header
echo "<<<plugin_section_name>>>"

# Output data in a parseable format
echo "key: value"
echo "metric: 123"
```

**Key points:**
- Section names use three angle brackets: `<<<section_name>>>`
- Output should be deterministic and parseable
- Avoid interactive prompts
- Handle errors gracefully (don't crash)
- Exit silently if not applicable (check if on correct system)

## Plugin Development Guidelines

### Creating a New Plugin

1. **Choose appropriate filename**
   - Use descriptive names: `system_type_check`
   - Linux plugins: no extension or `.sh`
   - Windows plugins: `.ps1` extension

2. **Add system detection**
   ```bash
   # Exit early if not on target system
   if [ ! -f /etc/system-specific-file ]; then
       exit 0
   fi
   ```

3. **Create section headers**
   ```bash
   echo "<<<system_info>>>"
   echo "<<<system_services>>>"
   ```

4. **Output parseable data**
   ```bash
   # Good - structured data
   echo "service_name: status"
   echo "metric_name: value"
   
   # Avoid - unstructured output
   echo "Service is running"
   ```

5. **Handle errors gracefully**
   ```bash
   # Don't crash on errors
   VALUE=$(command 2>/dev/null || echo "unavailable")
   echo "metric: $VALUE"
   ```

6. **Test thoroughly**
   ```bash
   # Test the plugin directly
   sudo ./your_plugin
   
   # Test via agent
   sudo check_mk_agent | grep "<<<your_section>>>"
   ```

### Testing Plugins

Before submitting:

1. **Syntax check**
   ```bash
   bash -n your_plugin.sh
   shellcheck your_plugin.sh  # if available
   ```

2. **Manual execution**
   ```bash
   sudo /usr/lib/check_mk_agent/plugins/your_plugin
   ```

3. **Agent integration**
   ```bash
   sudo check_mk_agent | grep "<<<your_section>>>"
   ```

4. **CheckMK service discovery**
   - Deploy to test system
   - Run service discovery in CheckMK GUI
   - Verify services are discovered

5. **Documentation**
   - Update README.md with plugin description
   - Add deployment instructions to DEPLOYMENT_GUIDE.md
   - Include example output

## Documentation Guidelines

### Update Documentation When:
- Adding new plugins
- Changing existing functionality
- Adding new bootstrap scripts
- Modifying configuration options

### Documentation Structure:
- Clear and concise descriptions
- Step-by-step instructions
- Code examples with comments
- Common troubleshooting scenarios

### Markdown Style:
- Use proper heading hierarchy (H1, H2, H3)
- Code blocks with language specification
- Lists for sequential steps
- Tables for comparison data

## Bootstrap Scripts

When adding or modifying bootstrap scripts:

1. **Naming convention**
   - Use numeric prefix: `XX-description.sh`
   - Keep order logical (10, 20, 30...)

2. **Error handling**
   ```bash
   set -euo pipefail
   ```

3. **User feedback**
   ```bash
   echo "==> Starting task"
   echo "✅ Task completed"
   echo "⚠️  Warning message"
   echo "❌ Error message"
   ```

4. **Idempotency**
   - Scripts should be safe to run multiple times
   - Check if already configured before making changes
   ```bash
   if [ ! -f /etc/configured ]; then
       # Configure
       touch /etc/configured
   fi
   ```

5. **Add to main bootstrap**
   Update `00_bootstrap.sh`:
   ```bash
   run XX-new-script.sh
   ```

## Pull Request Guidelines

### Before Submitting:
- [ ] Code follows style guidelines
- [ ] All tests pass
- [ ] Documentation is updated
- [ ] Commit messages are clear
- [ ] Changes are tested on target systems

### PR Description Should Include:
- Summary of changes
- Motivation and context
- Testing performed
- Related issues (if any)
- Screenshots (for UI changes)

### PR Review Process:
1. Automated checks must pass
2. Code review by maintainers
3. Testing in development environment
4. Documentation review
5. Merge to main branch

## Community

### Communication:
- GitHub Issues for bugs and features
- Pull Requests for code contributions
- Discussions for questions and ideas

### Code of Conduct:
- Be respectful and inclusive
- Focus on constructive feedback
- Help others learn and grow
- Follow community guidelines

## License

By contributing, you agree that your contributions will be licensed under the same license as the project.

## Questions?

If you have questions about contributing:
1. Check existing issues and documentation
2. Create a new issue with your question
3. Tag with "question" label

Thank you for contributing to CheckMK Tools!
