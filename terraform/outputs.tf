output "public_ip" {
  description = "Public IP of the pipeline server"
  value       = aws_eip.pipeline.public_ip
}

output "url" {
  description = "URL of the dashboard"
  value       = "http://${aws_eip.pipeline.public_ip}"
}

output "ssh" {
  description = "SSH command to connect"
  value       = "ssh -i ~/.ssh/${var.key_name}.pem ec2-user@${aws_eip.pipeline.public_ip}"
}
