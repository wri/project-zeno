"""Sector configuration for user profiles."""

SECTORS = {
    "gov": "Government",
    "ngo": "NGO/Non-Profit",
    "research": "Research/Academia", 
    "private": "Private Sector",
    "consulting": "Consulting",
    "media": "Media/Journalism",
    "education": "Education",
    "other": "Other"
}

# Mapping of sectors to their available roles
SECTOR_ROLES = {
    "gov": {
        "policy": "Policy Maker",
        "analyst": "Government Analyst", 
        "manager": "Program Manager",
        "technical": "Technical Specialist",
        "other": "Other Government Role"
    },
    "ngo": {
        "program": "Program Officer",
        "research": "Research Coordinator",
        "advocacy": "Advocacy Specialist",
        "communications": "Communications Specialist", 
        "director": "Director/Leadership",
        "other": "Other NGO Role"
    },
    "research": {
        "researcher": "Researcher",
        "professor": "Professor/Faculty",
        "student": "Graduate Student",
        "postdoc": "Post-doctoral Researcher",
        "technician": "Research Technician",
        "other": "Other Academic Role"
    },
    "private": {
        "analyst": "Business Analyst",
        "consultant": "Consultant",
        "manager": "Project Manager",
        "developer": "Developer",
        "sustainability": "Sustainability Specialist",
        "other": "Other Private Sector Role"
    },
    "consulting": {
        "environmental": "Environmental Consultant",
        "gis": "GIS Consultant",
        "strategy": "Strategy Consultant",
        "technical": "Technical Consultant",
        "other": "Other Consulting Role"
    },
    "media": {
        "journalist": "Journalist",
        "editor": "Editor",
        "producer": "Producer",
        "freelancer": "Freelancer",
        "other": "Other Media Role"
    },
    "education": {
        "teacher": "Teacher",
        "trainer": "Trainer",
        "curriculum": "Curriculum Developer",
        "admin": "Education Administrator",
        "other": "Other Education Role"
    },
    "other": {
        "other": "Other"
    }
}