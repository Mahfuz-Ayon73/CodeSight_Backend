package com.codesight.codesight.app.organization.services;

import java.util.UUID;

import org.springframework.stereotype.Service;

@Service
public class OrganizationService {

    public String getOrganizationName(UUID id) {
        return "CodeSight Organization #" + id;
    }
}
