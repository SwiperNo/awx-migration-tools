import requests
import urllib3
import getpass
import argparse
import json

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# URLs
TOWER_URL = '<tower-instance>'
AWX_URL = '<awx or aap instance>'
output_file = 'comparison_output.txt'

def deep_compare(obj1, obj2, path=""):
    differences = []
    if isinstance(obj1, dict) and isinstance(obj2, dict):
        for key in obj1.keys():
            if key not in obj2:
                differences.append(f"{path}: Key {key} found in Tower, but not in AWX.")
                continue
            differences += deep_compare(obj1[key], obj2[key], path=f"{path}.{key}")
        for key in obj2.keys():
            if key not in obj1:
                differences.append(f"{path}: Key {key} found in AWX, but not in Tower.")
    elif isinstance(obj1, list) and isinstance(obj2, list):
        if len(obj1) != len(obj2):
            differences.append(f"{path}: Mismatch. Different lengths. Tower: {len(obj1)}, AWX: {len(obj2)}")
            return differences
        for i, (item1, item2) in enumerate(zip(obj1, obj2)):
            differences += deep_compare(item1, item2, path=f"{path}[{i}]")
    else:
        if obj1 != obj2:
            differences.append(f"{path}: Mismatch. Tower: {obj1}, AWX: {obj2}")
    return differences

def fetch_resource_counts(base_url, auth_credentials, resource_type):
    resource_url = f'{base_url}/api/v2/{resource_type}/'
    resource_counts = {}
    
    while resource_url:
        print(f"\nFetching {resource_type} from {resource_url}")
        response = requests.get(resource_url, auth=auth_credentials, verify=False)
        response.raise_for_status()
        data = response.json()
        resource_url = data.get('next')
        
        if resource_url:
            resource_url = base_url + resource_url

        resources = data['results']
        for resource in resources:
            if resource_type == 'job_templates':
                credential_url = resource.get('related', {}).get('credentials')
                credentials_list = []
                if credential_url:
                    cred_response = requests.get(base_url + credential_url, auth=auth_credentials, verify=False)
                    cred_response.raise_for_status()
                    cred_data = cred_response.json()
                    credentials_list = [cred.get('name') for cred in cred_data['results']]
                resource_counts[resource['name'].lower().strip()] = credentials_list
                
            elif resource_type == 'schedules':
                unified_job_template_url = resource.get('related', {}).get('unified_job_template')
                named_url = None
                if unified_job_template_url:
                    job_template_url = f"{base_url}{unified_job_template_url}"
                    job_template_response = requests.get(job_template_url, auth=auth_credentials, verify=False)
                    job_template_response.raise_for_status()
                    job_template_data = job_template_response.json()
                    named_url = job_template_data.get('related', {}).get('named_url')
                resource_counts[resource['name'].lower().strip()] = named_url
                
            elif resource_type == 'credentials':
                credential_inputs = resource.get('inputs', {})
                resource_counts[resource['name'].lower().strip()] = credential_inputs

            elif resource_type == 'inventories':
                host_url = resource.get('related', {}).get('hosts')
                host_count = 0
                if host_url:
                    host_response = requests.get(base_url + host_url, auth=auth_credentials, verify=False)
                    host_response.raise_for_status()
                    host_data = host_response.json()
                    host_count = host_data.get('count', 0)  # get the host count
                resource_counts[resource['name'].lower().strip()] = host_count

            else:
                resource_counts[resource['name'].lower().strip()] = True
                
    return resource_counts

def compare_resources(tower_counts, awx_counts, resource_name):
    with open(output_file, 'a') as f:
        print(f"\nComparing {resource_name}...")
        f.write(f"\nComparing {resource_name}...\n")
        
        print(f"Debug: Tower Counts: {sorted(tower_counts.keys())}")
        print(f"Debug: AWX Counts: {sorted(awx_counts.keys())}")
        f.write(f"Debug: Tower Counts: {sorted(tower_counts.keys())}\n")
        f.write(f"Debug: AWX Counts: {sorted(awx_counts.keys())}\n")
        
        # Specific block for comparing inventory host counts
        if resource_name == 'inventories':
            for name, host_count in tower_counts.items():
                awx_host_count = awx_counts.get(name, 0)
                if host_count != awx_host_count:
                    output = f"Inventory '{name}' has {host_count} hosts in Tower but {awx_host_count} hosts in AWX."
                    print(output)
                    f.write(output + "\n")
        
        # Additional deep comparison for job templates and schedules:
        if resource_name in ['job_templates', 'schedules']:
            for name, details in tower_counts.items():
                awx_details = awx_counts.get(name)
                if details and awx_details:
                    differences = deep_compare(details, awx_details, path=f"{resource_name}.{name}")
                    if differences:
                        output = f"{resource_name[:-1].capitalize()} '{name}' has differences:\n" + '\n'.join(differences)
                        print(output)
                        f.write(output + "\n")
        
        # Rest of the comparisons (existing code with new mismatch messages for job templates)
        for name, value in tower_counts.items():
            if name not in awx_counts:
                extra_info = ""
                if isinstance(value, list):  # For job templates
                    extra_info = f" (Details: {', '.join(value)})"
                elif isinstance(value, dict):  # For credentials
                    extra_info = f" (Details: {json.dumps(value, indent=2)})"
                output = f"{resource_name[:-1].capitalize()} '{name}' exists in Tower but not in AWX.{extra_info}"
                print(output)
                f.write(output + "\n")
        
        for name, value in awx_counts.items():
            if name not in tower_counts:
                extra_info = ""
                if isinstance(value, list):  # For job templates
                    extra_info = f" (Details: {', '.join(value)})"
                elif isinstance(value, dict):  # For credentials
                    extra_info = f" (Details: {json.dumps(value, indent=2)})"
                output = f"{resource_name[:-1].capitalize()} '{name}' exists in AWX but not in Tower.{extra_info}"
                print(output)
                f.write(output + "\n")

def main():
    parser = argparse.ArgumentParser(description="Compare resources between AWX and Tower instances.")
    parser.add_argument("--username", help="The username for AWX and Tower.", required=True)
    args = parser.parse_args()
    password = getpass.getpass(f"Enter the password for {args.username}: ")
    AUTH = (args.username, password)
    
    with open(output_file, 'w') as f:
        f.write("Comparison between Tower and AWX\n")
        
    tower_inventory_counts = fetch_resource_counts(TOWER_URL, AUTH, "inventories")
    awx_inventory_counts = fetch_resource_counts(AWX_URL, AUTH, "inventories")
    compare_resources(tower_inventory_counts, awx_inventory_counts, "inventories")
    
    tower_template_counts = fetch_resource_counts(TOWER_URL, AUTH, "job_templates")
    awx_template_counts = fetch_resource_counts(AWX_URL, AUTH, "job_templates")
    compare_resources(tower_template_counts, awx_template_counts, "job_templates")
    
    tower_schedule_counts = fetch_resource_counts(TOWER_URL, AUTH, "schedules")
    awx_schedule_counts = fetch_resource_counts(AWX_URL, AUTH, "schedules")
    compare_resources(tower_schedule_counts, awx_schedule_counts, "schedules")
    
    tower_credential_counts = fetch_resource_counts(TOWER_URL, AUTH, "credentials")
    awx_credential_counts = fetch_resource_counts(AWX_URL, AUTH, "credentials")
    compare_resources(tower_credential_counts, awx_credential_counts, "credentials")

if __name__ == "__main__":
    main()
