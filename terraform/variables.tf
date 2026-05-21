variable "aws_region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "us-east-1"
}

variable "instance_type" {
  description = "EC2 instance type"
  type        = string
  default     = "t3.small"
}

variable "key_name" {
  description = "Name of an existing EC2 key pair for SSH access"
  type        = string
}

variable "api_image" {
  description = "Full API Docker image tag (e.g. ghcr.io/you/repo/api:latest)"
  type        = string
}

variable "nginx_image" {
  description = "Full nginx Docker image tag (e.g. ghcr.io/you/repo/nginx:latest)"
  type        = string
}

variable "postgres_user" {
  description = "PostgreSQL username"
  type        = string
  default     = "pipeline"
}

variable "postgres_password" {
  description = "PostgreSQL password"
  type        = string
  sensitive   = true
}

variable "allowed_ssh_cidr" {
  description = "CIDR block allowed to SSH (default: your IP only)"
  type        = string
  default     = "0.0.0.0/0"
}
