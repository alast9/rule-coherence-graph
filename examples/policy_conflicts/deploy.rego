package deploy

import rego.v1

# Auto-deploy to the production environment is denied: every production
# release goes through a human-approved change request.
deny contains msg if {
    input.action == "deploy"
    input.environment == "production"
    msg := "auto-deploy to production is not allowed"
}

# By default no deploy request is allowed until a rule grants it.
default allow := false
