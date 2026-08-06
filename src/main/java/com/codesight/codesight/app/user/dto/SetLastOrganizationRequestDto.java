package com.codesight.codesight.app.user.dto;

import jakarta.validation.constraints.NotNull;
import lombok.Data;

import java.util.UUID;

@Data
public class SetLastOrganizationRequestDto {

    @NotNull(message = "organizationId is required")
    private UUID organizationId;
}
