# CheckMK Installer - Testing Guide

## 🧪 Test Environment

### Prerequisites
- Vagrant (≥2.3.0)
- VirtualBox (≥7.0)
- At least 5GB free disk space
- At least 4GB RAM

### Quick Start

1. **Start test VM:**
   ```bash
   cd testing/
   vagrant up
   ```

2. **Run all tests:**
   ```bash
   vagrant ssh -c 'sudo /root/checkmk-installer/testing/test-vm.sh'
   ```

3. **Clean up:**
   ```bash
   vagrant destroy -f
   ```

## 📋 Test Scenarios

### Full Server Installation
Tests complete CheckMK server deployment:
```bash
vagrant ssh
sudo /root/checkmk-installer/testing/test-scenarios/full-server.sh
```

**What it tests:**
- System base configuration (SSH, NTP, UFW, Fail2Ban)
- CheckMK server installation and site creation
- Local agent installation
- Scripts deployment
- Ydea toolkit integration
- FRPC client setup (if configured)

**Expected result:**
- CheckMK web UI accessible at http://localhost:5000/monitoring/
- Agent responding on port 6556
- All monitoring scripts deployed

### Client-Only Installation
Tests CheckMK agent-only deployment:
```bash
sudo /root/checkmk-installer/testing/test-scenarios/client-only.sh
```

**What it tests:**
- System base configuration
- Agent installation and socket configuration
- Basic scripts deployment

**Expected result:**
- Agent listening on port 6556
- No CheckMK server installed

### Scripts-Only Deployment
Tests standalone scripts deployment:
```bash
sudo /root/checkmk-installer/testing/test-scenarios/scripts-only.sh
```

**What it tests:**
- Deployment of all monitoring scripts to /opt/
- Update script creation
- Correct permissions and symlinks

**Expected result:**
- All script directories in /opt/
- Update script at /usr/local/bin/update-checkmk-scripts

### Ydea-Only Installation
Tests Ydea toolkit standalone:
```bash
sudo /root/checkmk-installer/testing/test-scenarios/ydea-only.sh
```

**What it tests:**
- Ydea toolkit installation
- Configuration and authentication
- Systemd timer setup
- Tracking file initialization

**Expected result:**
- Toolkit command available: `ydea-toolkit`
- Systemd timer active (if enabled)

## 🔍 Test Suite Details

### Automated Tests (`test-vm.sh`)

**Pre-flight checks:**
- Running as root
- Installer directory exists
- Scripts executable
- Minimum disk space (5GB)
- Minimum memory (1.5GB)

**Configuration tests:**
- Config wizard exists
- Template validation
- .env file creation and loading

**System base tests:**
- Module execution
- SSH service running
- UFW firewall active
- Fail2Ban running

**CheckMK agent tests:**
- Module execution
- Agent binary installed
- Socket listening on port 6556
- Agent responds to queries

**Scripts deployment tests:**
- Module execution
- Notification scripts deployed
- Tool scripts deployed
- Update script created

**Ydea toolkit tests:**
- Module execution
- Toolkit installed and executable
- Tracking file initialized

### Test Results

Tests generate two outputs:
1. **Log file:** `/tmp/checkmk-installer-test.log`
2. **JSON report:** `/tmp/test-results.json`

JSON report format:
```json
{
  "timestamp": "2025-06-08T10:30:00Z",
  "total_tests": 25,
  "passed": 23,
  "failed": 2,
  "pass_rate": 92,
  "log_file": "/tmp/checkmk-installer-test.log"
}
```

## 🐛 Troubleshooting Tests

### VM won't start
```bash
# Check VirtualBox
VBoxManage list vms
VBoxManage list runningvms

# Check Vagrant status
vagrant status
vagrant global-status

# Force clean
vagrant destroy -f
vagrant box update
```

### Tests fail immediately
```bash
# Check logs
vagrant ssh
sudo cat /tmp/checkmk-installer-test.log

# Check installer permissions
sudo ls -la /root/checkmk-installer/
sudo chmod +x /root/checkmk-installer/*.sh
```

### Network issues
```bash
# Check port forwarding
vagrant port

# Reload VM networking
vagrant reload
```

### CheckMK not accessible
```bash
# Check site status
vagrant ssh
sudo omd status

# Check Apache
sudo systemctl status apache2

# Check logs
sudo tail -f /omd/sites/monitoring/var/log/web.log
```

## 📊 Performance Benchmarks

Approximate test execution times:
- Full server installation: 15-20 minutes
- Client-only installation: 5-8 minutes
- Scripts-only deployment: 2-3 minutes
- Ydea-only installation: 3-5 minutes
- Complete test suite: 25-30 minutes

## 🔄 Continuous Testing

### Manual testing workflow:
1. Make changes to installer
2. `vagrant destroy -f && vagrant up`
3. `vagrant ssh -c 'sudo /root/checkmk-installer/testing/test-vm.sh'`
4. Review results
5. Iterate

### Automated CI/CD (future):
- GitHub Actions integration
- Scheduled nightly tests
- Pull request validation
- Multi-distro testing (Ubuntu 22.04, 24.04, Debian 12)

## ✅ Test Checklist

Before release, verify:
- [ ] All automated tests pass (100%)
- [ ] Full server installation works
- [ ] Client-only installation works
- [ ] Scripts-only deployment works
- [ ] Ydea-only installation works
- [ ] ISO boots successfully
- [ ] USB installation works
- [ ] Configuration wizard completes
- [ ] All modules are idempotent
- [ ] Logging works correctly
- [ ] Error handling is robust
- [ ] Documentation is accurate
