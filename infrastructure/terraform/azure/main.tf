# Cloud side of the hybrid edge/cloud design: the Raspberry Pi keeps controlling Room 101 on its own; this VM
# hosts ML (MLflow, ML API), telemetry storage (ingestion + PostgreSQL) and monitoring. Low-cost choices
# throughout (B-series VM, ACR Basic, LRS storage, 30-day logs, budget alert).

data "azurerm_client_config" "current" {}

resource "random_string" "suffix" {
  length  = 5
  upper   = false
  special = false
}

locals {
  name = "${var.prefix}-${random_string.suffix.result}"
  flat = "${var.prefix}${random_string.suffix.result}" # for names without dashes (ACR, storage, Key Vault)
}

resource "azurerm_resource_group" "rg" {
  name     = "rg-${local.name}"
  location = var.location
  tags     = var.tags
}

# ------------------------------------------------------------------ network
resource "azurerm_virtual_network" "vnet" {
  name                = "vnet-${local.name}"
  address_space       = ["10.20.0.0/16"]
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  tags                = var.tags
}

resource "azurerm_subnet" "app" {
  name                 = "snet-app"
  resource_group_name  = azurerm_resource_group.rg.name
  virtual_network_name = azurerm_virtual_network.vnet.name
  address_prefixes     = ["10.20.1.0/24"]
  service_endpoints    = ["Microsoft.Storage", "Microsoft.KeyVault", "Microsoft.ContainerRegistry"]
}

resource "azurerm_network_security_group" "app" {
  name                = "nsg-${local.name}"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  tags                = var.tags

  security_rule {
    name                       = "ssh-admin-only"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "22"
    source_address_prefix      = var.admin_cidr
    destination_address_prefix = "*"
  }
  security_rule {
    name                       = "https-admin-only" # reverse proxy in front of Grafana / MLflow / ML API
    priority                   = 110
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = var.admin_cidr
    destination_address_prefix = "*"
  }
  security_rule {
    name                       = "mqtt-tls-edge-only" # the Pi's Mosquitto bridge (TLS + password + ACL)
    priority                   = 120
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "8883"
    source_address_prefix      = var.edge_cidr
    destination_address_prefix = "*"
  }
  security_rule {
    name                       = "deny-other-inbound"
    priority                   = 4000
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "Internet"
    destination_address_prefix = "*"
  }
}

resource "azurerm_subnet_network_security_group_association" "app" {
  subnet_id                 = azurerm_subnet.app.id
  network_security_group_id = azurerm_network_security_group.app.id
}

resource "azurerm_public_ip" "vm" {
  name                = "pip-${local.name}"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  allocation_method   = "Static"
  sku                 = "Standard"
  tags                = var.tags
}

resource "azurerm_network_interface" "vm" {
  name                = "nic-${local.name}"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  tags                = var.tags
  ip_configuration {
    name                          = "primary"
    subnet_id                     = azurerm_subnet.app.id
    private_ip_address_allocation = "Dynamic"
    public_ip_address_id          = azurerm_public_ip.vm.id
  }
}

# ------------------------------------------------------------------ compute
resource "azurerm_linux_virtual_machine" "vm" {
  name                            = "vm-${local.name}"
  location                        = azurerm_resource_group.rg.location
  resource_group_name             = azurerm_resource_group.rg.name
  size                            = var.vm_size
  admin_username                  = var.admin_username
  disable_password_authentication = true
  network_interface_ids           = [azurerm_network_interface.vm.id]
  tags                            = var.tags

  admin_ssh_key {
    username   = var.admin_username
    public_key = var.ssh_public_key
  }
  os_disk {
    name                 = "osdisk-${local.name}"
    caching              = "ReadWrite"
    storage_account_type = "StandardSSD_LRS"
    disk_size_gb         = 64
  }
  source_image_reference {
    publisher = "Canonical"
    offer     = "ubuntu-24_04-lts"
    sku       = "server"
    version   = "latest"
  }
  identity {
    type = "SystemAssigned" # pulls images from ACR and reads Key Vault secrets without stored credentials
  }
  boot_diagnostics {}
  custom_data = base64encode(templatefile("${path.module}/templates/cloud-init.yaml", {
    admin_username = var.admin_username
    repo_url       = var.repo_url
    acr_server     = azurerm_container_registry.acr.login_server
    key_vault_name = azurerm_key_vault.kv.name
  }))
}

# ------------------------------------------------------------------ registry, secrets, storage, logs
resource "azurerm_container_registry" "acr" {
  name                = "acr${local.flat}"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  sku                 = "Basic"
  admin_enabled       = false
  tags                = var.tags
}

resource "azurerm_role_assignment" "vm_acr_pull" {
  scope                = azurerm_container_registry.acr.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_linux_virtual_machine.vm.identity[0].principal_id
}

resource "azurerm_key_vault" "kv" {
  name                       = "kv-${local.flat}"
  location                   = azurerm_resource_group.rg.location
  resource_group_name        = azurerm_resource_group.rg.name
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  enable_rbac_authorization  = true
  purge_protection_enabled   = false
  soft_delete_retention_days = 7
  tags                       = var.tags
  # Secret VALUES are not created here (they would land in the state file): set them with
  #   az keyvault secret set --vault-name <kv> --name POSTGRES-PASSWORD --value ...
}

resource "azurerm_role_assignment" "vm_kv_read" {
  scope                = azurerm_key_vault.kv.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_linux_virtual_machine.vm.identity[0].principal_id
}

resource "azurerm_role_assignment" "deployer_kv_admin" {
  scope                = azurerm_key_vault.kv.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azurerm_client_config.current.object_id
}

resource "azurerm_storage_account" "backups" {
  name                            = "st${local.flat}"
  resource_group_name             = azurerm_resource_group.rg.name
  location                        = azurerm_resource_group.rg.location
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  min_tls_version                 = "TLS1_2"
  https_traffic_only_enabled      = true
  allow_nested_items_to_be_public = false
  shared_access_key_enabled       = false # Entra ID (managed identity) access only
  tags                            = var.tags
  blob_properties {
    delete_retention_policy { days = 7 }
  }
}

resource "azurerm_storage_container" "backups" {
  name                  = "backups"
  storage_account_id    = azurerm_storage_account.backups.id
  container_access_type = "private"
}

resource "azurerm_role_assignment" "vm_backup_writer" {
  scope                = azurerm_storage_account.backups.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_linux_virtual_machine.vm.identity[0].principal_id
}

resource "azurerm_log_analytics_workspace" "logs" {
  name                = "log-${local.name}"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  daily_quota_gb      = 0.5 # hard cap on ingestion cost
  tags                = var.tags
}

resource "azurerm_monitor_diagnostic_setting" "kv" {
  name                       = "kv-to-logs"
  target_resource_id         = azurerm_key_vault.kv.id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.logs.id
  enabled_log { category = "AuditEvent" }
}

resource "azurerm_monitor_metric_alert" "vm_cpu" {
  name                = "alert-${local.name}-cpu"
  resource_group_name = azurerm_resource_group.rg.name
  scopes              = [azurerm_linux_virtual_machine.vm.id]
  description         = "VM CPU above 85 % for 15 minutes"
  severity            = 2
  frequency           = "PT5M"
  window_size         = "PT15M"
  criteria {
    metric_namespace = "Microsoft.Compute/virtualMachines"
    metric_name      = "Percentage CPU"
    aggregation      = "Average"
    operator         = "GreaterThan"
    threshold        = 85
  }
  action { action_group_id = azurerm_monitor_action_group.owner.id }
}

resource "azurerm_monitor_action_group" "owner" {
  name                = "ag-${local.name}"
  resource_group_name = azurerm_resource_group.rg.name
  short_name          = "sbowner"
  email_receiver {
    name          = "owner"
    email_address = var.budget_email
  }
}

resource "azurerm_consumption_budget_resource_group" "monthly" {
  name              = "budget-${local.name}"
  resource_group_id = azurerm_resource_group.rg.id
  amount            = var.budget_amount
  time_grain        = "Monthly"
  time_period {
    start_date = formatdate("YYYY-MM-01'T'00:00:00Z", timestamp())
  }
  dynamic "notification" {
    for_each = [50, 80, 100]
    content {
      enabled        = true
      threshold      = notification.value
      operator       = "GreaterThanOrEqualTo"
      contact_emails = [var.budget_email]
    }
  }
  lifecycle { ignore_changes = [time_period] }
}
