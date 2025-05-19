#!/usr/bin/env python3
"""
start_services.py

This script starts the Supabase stack first, waits for it to initialize, and then starts
the local AI stack. Both stacks use the same Docker Compose project name ("localai")
so they appear together in Docker Desktop.
"""

import os
import subprocess
import shutil
import time
import argparse
import platform
import sys

def run_command(cmd, cwd=None):
    """Run a shell command and print it."""
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True)

def clone_supabase_repo():
    """Clone the Supabase repository using sparse checkout if not already present."""
    if not os.path.exists("supabase"):
        print("Cloning the Supabase repository...")
        run_command([
            "git", "clone", "--filter=blob:none", "--no-checkout",
            "https://github.com/supabase/supabase.git"
        ])
        os.chdir("supabase")
        run_command(["git", "sparse-checkout", "init", "--cone"])
        run_command(["git", "sparse-checkout", "set", "docker"])
        run_command(["git", "checkout", "master"])
        os.chdir("..")
    else:
        print("Supabase repository already exists, updating...")
        os.chdir("supabase")
        run_command(["git", "pull"])
        os.chdir("..")

def prepare_supabase_env():
    """Copy .env to .env in supabase/docker."""
    env_path = os.path.join("supabase", "docker", ".env")
    env_example_path = os.path.join(".env")
    print("Copying .env in root to .env in supabase/docker...")
    shutil.copyfile(env_example_path, env_path)

def stop_existing_containers(profile=None):
    print("Stopping and removing existing containers for the unified project 'localai'...")
    cmd = ["docker", "compose", "-p", "localai"]
    if profile and profile != "none":
        cmd.extend(["--profile", profile])
    cmd.extend(["-f", "docker-compose.yml", "down"])
    run_command(cmd)

def start_supabase():
    """Start the Supabase services (using its compose file)."""
    print("Starting Supabase services...")
    run_command([
        "docker", "compose", "-p", "localai", "-f", "supabase/docker/docker-compose.yml", "up", "-d"
    ])

def start_local_ai(profile=None):
    """Start the local AI services (using its compose file)."""
    print("Starting local AI services...")
    cmd = ["docker", "compose", "-p", "localai"]
    if profile and profile != "none":
        cmd.extend(["--profile", profile])
    cmd.extend(["-f", "docker-compose.yml", "up", "-d"])
    run_command(cmd)

def generate_searxng_secret_key():
    """Generate a secret key for SearXNG based on the current platform."""
    print("Checking SearXNG settings...")
    
    # Define paths for SearXNG settings files
    settings_path = os.path.join("searxng", "settings.yml")
    settings_base_path = os.path.join("searxng", "settings-base.yml")
    
    # Check if settings-base.yml exists
    if not os.path.exists(settings_base_path):
        print(f"Warning: SearXNG base settings file not found at {settings_base_path}")
        return
    
    # Check if settings.yml exists, if not create it from settings-base.yml
    if not os.path.exists(settings_path):
        print(f"SearXNG settings.yml not found. Creating from {settings_base_path}...")
        try:
            shutil.copyfile(settings_base_path, settings_path)
            print(f"Created {settings_path} from {settings_base_path}")
        except Exception as e:
            print(f"Error creating settings.yml: {e}")
            return
    else:
        print(f"SearXNG settings.yml already exists at {settings_path}")
    
    print("Generating SearXNG secret key...")
    
    # Detect the platform and run the appropriate command
    system = platform.system()
    
    try:
        if system == "Windows":
            print("Detected Windows platform, using PowerShell to generate secret key...")
            # PowerShell command to generate a random key and replace in the settings file
            ps_command = [
                "powershell", "-Command",
                "$randomBytes = New-Object byte[] 32; " +
                "(New-Object Security.Cryptography.RNGCryptoServiceProvider).GetBytes($randomBytes); " +
                "$secretKey = -join ($randomBytes | ForEach-Object { \"{0:x2}\" -f $_ }); " +
                "(Get-Content searxng/settings.yml) -replace 'ultrasecretkey', $secretKey | Set-Content searxng/settings.yml"
            ]
            subprocess.run(ps_command, check=True)
            
        elif system == "Darwin":  # macOS
            print("Detected macOS platform, using sed command with empty string parameter...")
            # macOS sed command requires an empty string for the -i parameter
            openssl_cmd = ["openssl", "rand", "-hex", "32"]
            random_key = subprocess.check_output(openssl_cmd).decode('utf-8').strip()
            sed_cmd = ["sed", "-i", "", f"s|ultrasecretkey|{random_key}|g", settings_path]
            subprocess.run(sed_cmd, check=True)
            
        else:  # Linux and other Unix-like systems
            print("Detected Linux/Unix platform, using standard sed command...")
            # Standard sed command for Linux
            openssl_cmd = ["openssl", "rand", "-hex", "32"]
            random_key = subprocess.check_output(openssl_cmd).decode('utf-8').strip()
            sed_cmd = ["sed", "-i", f"s|ultrasecretkey|{random_key}|g", settings_path]
            subprocess.run(sed_cmd, check=True)
            
        print("SearXNG secret key generated successfully.")
        
    except Exception as e:
        print(f"Error generating SearXNG secret key: {e}")
        print("You may need to manually generate the secret key using the commands:")
        print("  - Linux: sed -i \"s|ultrasecretkey|$(openssl rand -hex 32)|g\" searxng/settings.yml")
        print("  - macOS: sed -i '' \"s|ultrasecretkey|$(openssl rand -hex 32)|g\" searxng/settings.yml")
        print("  - Windows (PowerShell):")
        print("    $randomBytes = New-Object byte[] 32")
        print("    (New-Object Security.Cryptography.RNGCryptoServiceProvider).GetBytes($randomBytes)")
        print("    $secretKey = -join ($randomBytes | ForEach-Object { \"{0:x2}\" -f $_ })")
        print("    (Get-Content searxng/settings.yml) -replace 'ultrasecretkey', $secretKey | Set-Content searxng/settings.yml")

def check_and_fix_docker_compose_for_searxng():
    """Check and modify docker-compose.yml for SearXNG first run."""
    docker_compose_path = "docker-compose.yml"
    if not os.path.exists(docker_compose_path):
        print(f"Warning: Docker Compose file not found at {docker_compose_path}")
        return
    
    try:
        # Read the docker-compose.yml file
        with open(docker_compose_path, 'r') as file:
            lines = file.readlines()
        
        # Default to first run
        is_first_run = True
        
        # Check if Docker is running and if the SearXNG container exists
        try:
            # Check if the SearXNG container is running
            container_check = subprocess.run(
                ["docker", "ps", "--filter", "name=searxng", "--format", "{{.Names}}"],
                capture_output=True, text=True, check=True
            )
            searxng_containers = container_check.stdout.strip().split('\n')
            
            # If SearXNG container is running, check inside for uwsgi.ini
            if any(container for container in searxng_containers if container):
                container_name = next(container for container in searxng_containers if container)
                print(f"Found running SearXNG container: {container_name}")
                
                # Check if uwsgi.ini exists inside the container
                container_check = subprocess.run(
                    ["docker", "exec", container_name, "sh", "-c", "[ -f /etc/searxng/uwsgi.ini ] && echo 'found' || echo 'not_found'"],
                    capture_output=True, text=True, check=False
                )
                
                if "found" in container_check.stdout:
                    print("Found uwsgi.ini inside the SearXNG container - not first run")
                    is_first_run = False
                else:
                    print("uwsgi.ini not found inside the SearXNG container - first run")
                    is_first_run = True
            else:
                print("No running SearXNG container found - assuming first run")
        except Exception as e:
            print(f"Error checking Docker container: {e} - assuming first run")
        
        # Find the SearXNG section and modify cap_drop if needed
        in_searxng_section = False
        searxng_section_indent = 0
        cap_drop_line_index = -1
        cap_drop_value_line_index = -1
        
        # First pass: find the SearXNG section and cap_drop lines
        for i, line in enumerate(lines):
            # Check for searxng section start
            if "searxng:" in line and not in_searxng_section:
                in_searxng_section = True
                searxng_section_indent = len(line) - len(line.lstrip())
                continue
            
            # If we're in the searxng section
            if in_searxng_section:
                # Check if we've moved out of the searxng section (less or equal indentation)
                current_indent = len(line) - len(line.lstrip())
                if line.strip() and current_indent <= searxng_section_indent:
                    in_searxng_section = False
                    continue
                
                # Look for cap_drop line
                if "cap_drop:" in line and not line.strip().startswith('#'):
                    cap_drop_line_index = i
                # Look for - ALL line after cap_drop
                elif cap_drop_line_index != -1 and "- ALL" in line and not line.strip().startswith('#'):
                    cap_drop_value_line_index = i
                    break
        
        # Second pass: modify the lines if needed
        if is_first_run and cap_drop_line_index != -1 and cap_drop_value_line_index != -1:
            print("First run detected for SearXNG. Temporarily commenting out cap_drop directives...")
            # Comment out the cap_drop line
            lines[cap_drop_line_index] = lines[cap_drop_line_index].replace("cap_drop:", "# cap_drop: # Temporarily commented out for first run")
            # Comment out the - ALL line
            lines[cap_drop_value_line_index] = lines[cap_drop_value_line_index].replace("- ALL", "# - ALL # Temporarily commented out for first run")
            
            # Write the modified content back
            with open(docker_compose_path, 'w') as file:
                file.writelines(lines)
                
            print("Note: After the first run completes successfully, you should re-enable 'cap_drop: - ALL' in docker-compose.yml for security reasons.")
        elif not is_first_run:
            # Check if we need to uncomment the cap_drop directives
            commented_cap_drop_found = False
            commented_all_found = False
            
            for i, line in enumerate(lines):
                if "# cap_drop: # Temporarily commented out for first run" in line:
                    lines[i] = line.replace("# cap_drop: # Temporarily commented out for first run", "cap_drop:")
                    commented_cap_drop_found = True
                elif "# - ALL # Temporarily commented out for first run" in line:
                    lines[i] = line.replace("# - ALL # Temporarily commented out for first run", "- ALL")
                    commented_all_found = True
            
            if commented_cap_drop_found or commented_all_found:
                print("SearXNG has been initialized. Re-enabling 'cap_drop: - ALL' directive for security...")
                # Write the modified content back
                with open(docker_compose_path, 'w') as file:
                    file.writelines(lines)
    
    except Exception as e:
        print(f"Error checking/modifying docker-compose.yml for SearXNG: {e}")

def fix_supabase_realtime_healthcheck():
    """Fix the Supabase Realtime service healthcheck configuration.
    
    This addresses the 403 Forbidden errors in the Realtime service healthcheck by replacing
    the authenticated health check endpoint with a simple HTTP check to the root page.
    This approach works because the service is actually functioning properly despite
    the authentication issues with the health check endpoint.
    
    Testing has confirmed that while the protected endpoint consistently returns 403,
    the root URL is accessible and returns a 200 OK status, making it a reliable
    health check endpoint.
    """
    print("Checking and fixing Supabase Realtime healthcheck configuration...")
    
    # Path to the Supabase docker-compose.yml file
    docker_compose_path = os.path.join("supabase", "docker", "docker-compose.yml")
    
    if not os.path.exists(docker_compose_path):
        print(f"Warning: Supabase docker-compose.yml not found at {docker_compose_path}")
        return
    
    try:
        # Read the docker-compose.yml file
        with open(docker_compose_path, 'r') as file:
            content = file.read()
        
        # Check if the file contains the problematic health check configuration
        if '/api/tenants/realtime-dev/health' in content and 'healthcheck' in content and 'realtime-dev.supabase-realtime' in content:
            print("Found problematic Supabase Realtime healthcheck configuration. Replacing with a root URL HTTP check...")
            
            # Find the start and end of the health check configuration
            healthcheck_start = content.find('healthcheck:', content.find('realtime-dev.supabase-realtime'))
            environment_start = content.find('environment:', healthcheck_start)
            
            if healthcheck_start != -1 and environment_start != -1:
                # Extract and replace the health check section
                healthcheck_section = content[healthcheck_start:environment_start]
                
                # Create a new health check section that uses the root URL instead of the protected endpoint
                # Testing has confirmed that the root URL returns 200 OK without requiring authorization
                new_healthcheck = (
                    'healthcheck:\n'
                    '      test:\n'
                    '        [\n'
                    '          "CMD",\n'
                    '          "curl",\n'
                    '          "-sSfL",\n'
                    '          "--head",\n'
                    '          "-o",\n'
                    '          "/dev/null",\n'
                    '          "http://localhost:4000/"\n'
                    '        ]\n'
                    '      timeout: 5s\n'
                    '      interval: 5s\n'
                    '      retries: 3\n'
                )
                
                # Replace the health check section in the content
                modified_content = content.replace(healthcheck_section, new_healthcheck)
                
                # Write the modified content back to the file
                with open(docker_compose_path, 'w') as file:
                    file.write(modified_content)
                    
                print("Successfully updated Supabase Realtime healthcheck to use the root URL instead of the protected endpoint")
            else:
                print("Could not locate exact healthcheck and environment sections in the docker-compose.yml file")
        else:
            print("Supabase Realtime healthcheck is already using a non-authenticated configuration or not found")
    
    except Exception as e:
        print(f"Error fixing Supabase Realtime healthcheck: {e}")
        import traceback
        traceback.print_exc()

def main():
    parser = argparse.ArgumentParser(description='Start the local AI and Supabase services.')
    parser.add_argument('--profile', choices=['cpu', 'gpu-nvidia', 'gpu-amd', 'none'], default='cpu',
                      help='Profile to use for Docker Compose (default: cpu)')
    args = parser.parse_args()

    clone_supabase_repo()
    prepare_supabase_env()
    
    # Generate SearXNG secret key and check docker-compose.yml
    generate_searxng_secret_key()
    check_and_fix_docker_compose_for_searxng()
    
    # Fix Supabase Realtime healthcheck
    fix_supabase_realtime_healthcheck()
    
    stop_existing_containers(args.profile)
    
    # Start Supabase first
    start_supabase()
    
    # Give Supabase some time to initialize
    print("Waiting for Supabase to initialize...")
    time.sleep(10)
    
    # Then start the local AI services
    start_local_ai(args.profile)

if __name__ == "__main__":
    main()
