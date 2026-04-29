# CLI User Management Commands

This document describes the user management commands available in the Project Zeno CLI tool.

## Prerequisites

To run these commands, you need access to the Kubernetes cluster where Zeno is deployed. You'll execute the commands inside a running API pod.

## Command Execution

To run CLI commands, first get access to a running API pod:

```bash
kubectl exec $(kubectl get pods --no-headers | grep zeno-api | awk '{print $1}' | head -1) -- uv run python src/api/cli.py <command>
```

## Available Commands

### make-user-admin

Makes an existing user an administrator by updating their user type to admin.

**Usage:**
```bash
kubectl exec $(kubectl get pods --no-headers | grep zeno-api | awk '{print $1}' | head -1) -- uv run python src/api/cli.py make-user-admin --email admin@example.com
```

**Parameters:**
- `--email` (required): Email address of the user to make admin

**Output:**
```
✅ Made user admin:
   ID: user_123abc
   Name: John Doe
   Email: john.doe@company.com
   User Type: admin
   Updated: 2024-09-15 10:30:45
```

**Notes:**
- The user must already exist in the system
- This command changes their user type from regular user to admin
- Admin users have higher prompt quotas

## Error Handling

The command includes error handling:

- **make-user-admin**: Returns an error if the user with the specified email doesn't exist
