output "resource_group" { value = azurerm_resource_group.rg.name }
output "vm_public_ip" { value = azurerm_public_ip.vm.ip_address }
output "ssh" { value = "ssh ${var.admin_username}@${azurerm_public_ip.vm.ip_address}" }
output "acr_login_server" { value = azurerm_container_registry.acr.login_server }
output "key_vault_name" { value = azurerm_key_vault.kv.name }
output "backup_storage_account" { value = azurerm_storage_account.backups.name }
output "log_analytics_workspace_id" { value = azurerm_log_analytics_workspace.logs.workspace_id }
output "mqtt_bridge_endpoint" { value = "${azurerm_public_ip.vm.ip_address}:8883 (TLS)" }
