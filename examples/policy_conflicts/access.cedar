// Production data is protected: deleting resources in the production
// environment is never permitted, regardless of who requests it.
@id("forbid-prod-delete")
forbid(
    principal,
    action == Action::"DeleteObject",
    resource
)
when {
    resource.environment == "production"
};

// Read access to production resources is always allowed.
permit(
    principal,
    action == Action::"GetObject",
    resource
)
when {
    resource.environment == "production"
};
