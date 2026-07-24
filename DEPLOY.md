Here's the setup, run partly from your local machine and partly on the VPS over SSH:

1. Generate a keypair locally (skip if you already have one you want to reuse)


ssh-keygen -t ed25519 -f ~/.ssh/framewrite_vps -C "root@your-vps"
This makes ~/.ssh/framewrite_vps (private, keep secret) and ~/.ssh/framewrite_vps.pub (public).

2. Copy the public key to the VPS's root account


ssh-copy-id -i ~/.ssh/framewrite_vps.pub root@YOUR_VPS_IP
(If ssh-copy-id isn't available, manually append the .pub file's contents to /root/.ssh/authorized_keys on the VPS, creating that file/dir with chmod 700 ~/.ssh and chmod 600 ~/.ssh/authorized_keys.)

3. Confirm key login works BEFORE touching password auth


ssh -i ~/.ssh/framewrite_vps root@YOUR_VPS_IP
Don't proceed until this logs you in without a password prompt.

4. On the VPS, edit /etc/ssh/sshd_config — set/uncomment:


PubkeyAuthentication yes
PasswordAuthentication no
PermitRootLogin prohibit-password
PermitRootLogin prohibit-password is the key line — it keeps root login allowed, but only via key, never a password.

5. Restart sshd


sudo systemctl restart ssh
6. Critical safety check: open a brand-new terminal/SSH session (don't close your current one) and confirm you can still log in via the key before ending your original session. If something's misconfigured, your current session is your only way back in to fix it.


A couple of useful sanity checks while you're at it:


# confirms the actual unit name if you're ever unsure
systemctl list-units --type=service | grep -i ssh

# validates sshd_config syntax before restarting -- catches typos before they lock you out
sudo sshd -t
After that, same critical step as before: open a fresh terminal/SSH session and confirm key-only login still works before closing your current session.

