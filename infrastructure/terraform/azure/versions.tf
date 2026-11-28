terraform {
  required_version = ">= 1.6"
  required_providers {
    azurerm = { source = "hashicorp/azurerm", version = "~> 4.40" }
    random  = { source = "hashicorp/random", version = "~> 3.7" }
  }
  # State: local by default. For a team, copy backend.tf.example to backend.tf (Azure Storage, state locking).
}

provider "azurerm" {
  features {
    key_vault { purge_soft_delete_on_destroy = false }
    resource_group { prevent_deletion_if_contains_resources = true }
  }
  # Credentials never live here: az login locally, or OIDC (ARM_USE_OIDC, ARM_CLIENT_ID, ARM_TENANT_ID,
  # ARM_SUBSCRIPTION_ID) from GitHub Actions secrets.
}
