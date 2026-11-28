variable "prefix" {
  description = "Short name used in every resource name (letters and digits)."
  type        = string
  default     = "sbfyp"
  validation {
    condition     = can(regex("^[a-z][a-z0-9]{2,9}$", var.prefix))
    error_message = "3-10 lowercase letters or digits, starting with a letter."
  }
}

variable "location" {
  description = "Azure region (Azure for Students allows a limited set; Central India is closest to Sri Lanka)."
  type        = string
  default     = "centralindia"
}

variable "vm_size" {
  description = "Cloud VM: runs the container stack (MLflow, ML API, ingestion, PostgreSQL, monitoring)."
  type        = string
  default     = "Standard_B2s" # 2 vCPU, 4 GiB: the measured stack uses ~1.3 GiB
}

variable "admin_username" {
  type    = string
  default = "sbadmin"
}

variable "ssh_public_key" {
  description = "Public SSH key for the VM admin (password login is disabled)."
  type        = string
}

variable "admin_cidr" {
  description = "Your public IP in CIDR form (e.g. 203.0.113.7/32): SSH and the web UIs are open to it only."
  type        = string
  validation {
    condition     = can(cidrhost(var.admin_cidr, 0)) && var.admin_cidr != "0.0.0.0/0"
    error_message = "A valid CIDR that is not the whole Internet."
  }
}

variable "edge_cidr" {
  description = "Public IP of the Raspberry Pi's network: MQTT over TLS (8883) is open to it only."
  type        = string
  validation {
    condition     = can(cidrhost(var.edge_cidr, 0)) && var.edge_cidr != "0.0.0.0/0"
    error_message = "A valid CIDR that is not the whole Internet."
  }
}

variable "budget_amount" {
  description = "Monthly budget for the resource group in the subscription currency; alerts at 50/80/100 %."
  type        = number
  default     = 20
}

variable "budget_email" {
  description = "Where budget alerts go."
  type        = string
}

variable "repo_url" {
  description = "Repository the VM clones on first boot."
  type        = string
  default     = "https://github.com/Ravindu-VS/smartbuilding-FYP.git"
}

variable "tags" {
  type = map(string)
  default = {
    project = "smart-building-fyp"
    owner   = "kdu-final-year-project"
    env     = "demo"
  }
}
