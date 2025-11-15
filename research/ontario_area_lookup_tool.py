"""
Ontario Area Lookup Tool
=========================

A LangChain tool for searching Ontario areas including:
- Provincial Parks
- Conservation Reserves  
- Conservation Authorities
- Municipalities
- Watersheds
- Forest Management Units

This tool uses the unified search_ontario_areas() database function.
"""

from langchain.tools import BaseTool
from typing import Optional, Dict, Any, List
import json
import asyncpg
import os
import logging
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class OntarioAreaSearchInput(BaseModel):
    """Input schema for Ontario area search"""
    query: str = Field(description="Search query (area name, partial name, or keywords)")
    area_types: Optional[List[str]] = Field(
        default=None,
        description="Filter by area types: provincial_park, conservation_reserve, conservation_authority, municipality, watershed, fmu"
    )
    region: Optional[str] = Field(
        default=None,
        description="Ontario region: Southern Ontario, Central Ontario, Eastern Ontario, Northern Ontario, Far North"
    )
    limit: int = Field(default=10, description="Maximum number of results to return")


class OntarioAreaLookupTool(BaseTool):
    """Tool for searching Ontario areas of interest"""
    
    name = "ontario_area_lookup"
    description = """
    Search for areas of interest in Ontario including:
    - Provincial Parks (by name or park class)
    - Conservation Reserves
    - Conservation Authorities (by name, acronym, or watershed)
    - Municipalities (by name or county)
    - Watersheds (by name or drainage system)
    - Forest Management Units
    
    Examples:
    - "Algonquin" -> Finds Algonquin Provincial Park
    - "Grand River" -> Finds Grand River Conservation Authority and watershed
    - "Toronto" -> Finds City of Toronto
    - "wilderness parks northern ontario" -> Finds wilderness-class parks in Northern Ontario
    
    Input can be a simple search string or JSON with filters:
    {
        "query": "Algonquin",
        "area_types": ["provincial_park"],
        "region": "Central Ontario"
    }
    
    Returns JSON with search results including name, type, geometry, and size.
    """
    
    args_schema = OntarioAreaSearchInput
    
    # Database connection string from environment
    database_url: str = os.getenv("DATABASE_URL", "")
    
    async def _get_connection(self) -> asyncpg.Connection:
        """Get database connection"""
        return await asyncpg.connect(self.database_url)
    
    def _parse_input(self, query: str) -> Dict[str, Any]:
        """Parse input query (string or JSON)"""
        try:
            # Try to parse as JSON
            params = json.loads(query)
            return {
                "query": params.get("query", ""),
                "area_types": params.get("area_types", params.get("types")),
                "region": params.get("region"),
                "limit": params.get("limit", 10)
            }
        except json.JSONDecodeError:
            # Plain string query
            return {
                "query": query,
                "area_types": None,
                "region": None,
                "limit": 10
            }
    
    async def _execute_search(
        self, 
        query: str,
        area_types: Optional[List[str]] = None,
        region: Optional[str] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Execute search against database"""
        
        conn = await self._get_connection()
        
        try:
            # Call the unified search function
            results = await conn.fetch(
                """
                SELECT 
                    id, name, type, subtype, 
                    ST_AsGeoJSON(geometry) as geometry,
                    size_ha, relevance
                FROM search_ontario_areas($1, $2, $3, $4)
                """,
                query,
                area_types,
                region,
                limit
            )
            
            # Format results
            formatted_results = []
            for row in results:
                result = {
                    "id": row["id"],
                    "name": row["name"],
                    "type": row["type"],
                    "subtype": row["subtype"],
                    "geometry": json.loads(row["geometry"]) if row["geometry"] else None,
                    "size_ha": float(row["size_ha"]) if row["size_ha"] else None,
                    "size_km2": float(row["size_ha"]) / 100 if row["size_ha"] else None,
                    "relevance": float(row["relevance"]) if row["relevance"] else 0
                }
                
                # Add type-specific context
                if result["type"] == "provincial_park":
                    result["description"] = f"{result['name']} is a {result['subtype']} provincial park"
                elif result["type"] == "conservation_authority":
                    result["description"] = f"{result['name']} manages watersheds in its jurisdiction"
                elif result["type"] == "municipality":
                    result["description"] = f"{result['name']} is a {result['subtype']}"
                
                formatted_results.append(result)
            
            return formatted_results
            
        finally:
            await conn.close()
    
    async def _arun(self, query: str) -> str:
        """Execute search asynchronously"""
        try:
            # Parse input
            params = self._parse_input(query)
            
            logger.info(f"Ontario area search: {params['query']}")
            
            # Execute search
            results = await self._execute_search(
                query=params["query"],
                area_types=params["area_types"],
                region=params["region"],
                limit=params["limit"]
            )
            
            # Format response
            if not results:
                return json.dumps({
                    "status": "no_results",
                    "message": f"No Ontario areas found matching '{params['query']}'",
                    "results": []
                })
            
            # Create summary
            summary = self._create_summary(results, params["query"])
            
            response = {
                "status": "success",
                "query": params["query"],
                "count": len(results),
                "summary": summary,
                "results": results
            }
            
            return json.dumps(response, indent=2)
            
        except Exception as e:
            logger.error(f"Error in Ontario area lookup: {e}", exc_info=True)
            return json.dumps({
                "status": "error",
                "message": str(e)
            })
    
    def _run(self, query: str) -> str:
        """Synchronous execution (delegates to async)"""
        import asyncio
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(self._arun(query))
    
    def _create_summary(self, results: List[Dict[str, Any]], query: str) -> str:
        """Create human-readable summary of results"""
        
        if not results:
            return f"No areas found matching '{query}'"
        
        # Count by type
        type_counts = {}
        for result in results:
            type_name = result["type"].replace("_", " ").title()
            type_counts[type_name] = type_counts.get(type_name, 0) + 1
        
        # Build summary
        if len(results) == 1:
            result = results[0]
            if result["size_ha"]:
                return f"Found {result['name']}, a {result['subtype']} covering {result['size_km2']:.1f} km²"
            else:
                return f"Found {result['name']}, a {result['subtype']}"
        else:
            type_summary = ", ".join([f"{count} {type_name}(s)" for type_name, count in type_counts.items()])
            return f"Found {len(results)} areas matching '{query}': {type_summary}"


# Example tool for Conservation Authority specific queries
class ConservationAuthorityTool(BaseTool):
    """Tool for detailed Conservation Authority information"""
    
    name = "conservation_authority_info"
    description = """
    Get detailed information about Ontario Conservation Authorities.
    
    Conservation Authorities are watershed-based organizations that manage:
    - Flood control and floodplain mapping
    - Water quality monitoring
    - Conservation areas and natural spaces
    - Source water protection
    - Environmental education
    
    Input: Conservation Authority name or acronym (e.g., "Grand River Conservation Authority" or "GRCA")
    
    Returns: Detailed information including jurisdiction, watersheds, programs, and contact info.
    """
    
    database_url: str = os.getenv("DATABASE_URL", "")
    
    async def _get_ca_details(self, ca_name: str) -> Dict[str, Any]:
        """Get Conservation Authority details from database"""
        
        conn = await asyncpg.connect(self.database_url)
        
        try:
            # Search for CA by name or acronym
            ca = await conn.fetchrow(
                """
                SELECT 
                    authority_name, acronym, jurisdiction_area_ha,
                    watershed_count, municipalities_served, programs,
                    contact_email, website, established_year,
                    ST_AsGeoJSON(geometry) as geometry
                FROM ontario_conservation_authorities
                WHERE authority_name ILIKE '%' || $1 || '%'
                   OR acronym ILIKE '%' || $1 || '%'
                LIMIT 1
                """,
                ca_name
            )
            
            if not ca:
                return None
            
            # Get watersheds managed by this CA
            watersheds = await conn.fetch(
                """
                SELECT watershed_name, area_ha, primary_drainage
                FROM ontario_watersheds
                WHERE conservation_authority_id = (
                    SELECT id FROM ontario_conservation_authorities
                    WHERE authority_name = $1
                )
                """,
                ca["authority_name"]
            )
            
            # Format result
            result = {
                "name": ca["authority_name"],
                "acronym": ca["acronym"],
                "established": ca["established_year"],
                "jurisdiction_area_km2": float(ca["jurisdiction_area_ha"]) / 100 if ca["jurisdiction_area_ha"] else None,
                "watershed_count": ca["watershed_count"],
                "municipalities_served": ca["municipalities_served"],
                "programs": ca["programs"],
                "contact": {
                    "email": ca["contact_email"],
                    "website": ca["website"]
                },
                "watersheds": [
                    {
                        "name": w["watershed_name"],
                        "area_km2": float(w["area_ha"]) / 100 if w["area_ha"] else None,
                        "drains_to": w["primary_drainage"]
                    }
                    for w in watersheds
                ],
                "geometry": json.loads(ca["geometry"]) if ca["geometry"] else None
            }
            
            return result
            
        finally:
            await conn.close()
    
    async def _arun(self, query: str) -> str:
        """Execute CA lookup"""
        try:
            logger.info(f"Conservation Authority lookup: {query}")
            
            result = await self._get_ca_details(query)
            
            if not result:
                return json.dumps({
                    "status": "not_found",
                    "message": f"No Conservation Authority found matching '{query}'",
                    "note": "There are 36 Conservation Authorities in Ontario. Try searching by full name or acronym."
                })
            
            # Create summary
            summary = (
                f"{result['name']} ({result['acronym']}) manages {result['watershed_count']} "
                f"watershed(s) covering {result['jurisdiction_area_km2']:.0f} km². "
                f"It serves {len(result['municipalities_served'])} municipalities."
            )
            
            return json.dumps({
                "status": "success",
                "summary": summary,
                "details": result
            }, indent=2)
            
        except Exception as e:
            logger.error(f"Error in CA lookup: {e}", exc_info=True)
            return json.dumps({
                "status": "error",
                "message": str(e)
            })
    
    def _run(self, query: str) -> str:
        """Synchronous execution"""
        import asyncio
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(self._arun(query))


# Tool registry for easy import
ONTARIO_TOOLS = [
    OntarioAreaLookupTool(),
    ConservationAuthorityTool()
]


if __name__ == "__main__":
    """Test the tools"""
    import asyncio
    
    async def test_tools():
        # Test area lookup
        lookup_tool = OntarioAreaLookupTool()
        
        print("Testing Ontario Area Lookup Tool")
        print("=" * 80)
        
        # Test 1: Simple search
        result = await lookup_tool._arun("Algonquin")
        print("\nTest 1: Search for 'Algonquin'")
        print(result)
        
        # Test 2: JSON search with filters
        result = await lookup_tool._arun(json.dumps({
            "query": "Grand River",
            "area_types": ["conservation_authority", "watershed"]
        }))
        print("\nTest 2: Search for 'Grand River' (CAs and watersheds)")
        print(result)
        
        # Test Conservation Authority tool
        ca_tool = ConservationAuthorityTool()
        
        print("\n" + "=" * 80)
        print("Testing Conservation Authority Tool")
        print("=" * 80)
        
        result = await ca_tool._arun("GRCA")
        print("\nTest: Get info on GRCA")
        print(result)
    
    asyncio.run(test_tools())
