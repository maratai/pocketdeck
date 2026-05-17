# SSH and SCP

Pocket Deck supports SSH and SCP (SFTP) for connecting to remote machines.

## Authentication methods

Two authentication methods are supported: **password** and **RSA key**.

> **Note:** Pocket Deck uses libssh2, which only supports RSA keys. Modern key types such as Ed25519 are not supported. You must use an RSA key.

### Password authentication

Pass your password with the `-p` option:

```
ssh user@192.168.1.10 -p yourpassword
```

### RSA key authentication (recommended)

Key authentication is more secure and avoids typing a password each time.

**Step 1 — Generate an RSA key on your PC**

Run this on your PC (Linux/Mac terminal or Windows PowerShell):

```
ssh-keygen -t rsa -m PEM -f id_rsa
```

This creates two files:
- `id_rsa` — private key (goes on Pocket Deck)
- `id_rsa.pub` — public key (goes on your remote PC)

> The `-m PEM` flag is required. Without it, newer versions of `ssh-keygen` produce a format that libssh2 cannot read.

**Step 2 — Copy the public key to your remote PC**

Append `id_rsa.pub` to `~/.ssh/authorized_keys` on the machine you want to connect to:

```
cat id_rsa.pub >> ~/.ssh/authorized_keys
```

**Step 3 — Copy the private key to Pocket Deck**

Place `id_rsa` at `/config/ssh/id_rsa` on Pocket Deck. You can use the `scp` command or copy it via the SD card.

Once the key is in place, SSH and SCP will use it automatically — no `-p` option needed.

## Connecting to WSL (Windows Subsystem for Linux)

WSL2 runs inside a virtual machine with its own private IP address, so a few extra steps are needed before Pocket Deck can reach it.

### Step 1 — Install and start the SSH server in WSL

In your WSL terminal:

```
sudo apt update && sudo apt install -y openssh-server
sudo service ssh start
```

To make SSH start automatically when WSL launches, add the following line to your `~/.bashrc` (or `~/.profile`):

```
sudo service ssh start > /dev/null 2>&1
```

### Step 2 — Find the WSL IP address

In your WSL terminal:

```
hostname -I
```

Note the first IP address shown (e.g. `172.20.144.5`). This address changes every time WSL restarts, so you will need to repeat steps 3 and 4 when that happens.

### Step 3 — Forward port 22 from Windows to WSL

Run the following in **PowerShell as Administrator**, replacing `WSL_IP` with the address from step 2:

```powershell
netsh interface portproxy add v4tov4 listenport=22 listenaddress=0.0.0.0 connectport=22 connectaddress=WSL_IP
```

To check the current rule:

```powershell
netsh interface portproxy show all
```

To remove the rule (e.g. before adding a new one after WSL restarts):

```powershell
netsh interface portproxy delete v4tov4 listenport=22 listenaddress=0.0.0.0
```

### Step 4 — Open port 22 in Windows Firewall

Run once in **PowerShell as Administrator**:

```powershell
New-NetFirewallRule -DisplayName "WSL SSH" -Direction Inbound -Protocol TCP -LocalPort 22 -Action Allow
```

### Step 5 — Connect from Pocket Deck

Use your **Windows machine's IP address** (not the WSL IP) when connecting:

```
ssh user@192.168.1.10
```

Where `user` is your WSL username and `192.168.1.10` is the Windows host's IP on your local network (find it with `ipconfig` in PowerShell).

> **Reminder:** The WSL IP changes on every restart. When that happens, re-run step 3 to update the port forwarding rule.

## SSH

```
ssh user@192.168.1.10
ssh user@192.168.1.10 -p password
```

## SCP

Usage: `scp local user@host:remote` or `scp user@host:remote local`

```
# Copy from remote to local
scp user@192.168.1.10:/path/to/remote /path/to/local

# Copy from local to remote
scp /path/to/local user@192.168.1.10:/path/to/remote
```
