package com.codesight.codesight.app.user.dto;

import com.codesight.codesight.app.user.role.UserRole;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;
import java.time.LocalDateTime;
import java.util.UUID;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class UserResponseDto {
    private UUID id;
    private String email;
    private String username;
    private String firstName;
    private String lastName;
    private UserRole role;
    private boolean isEnabled;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
    /** Organization the user last switched to — used to resume in the same "tenant" on next login. */
    private UUID lastOrganizationId;
}
