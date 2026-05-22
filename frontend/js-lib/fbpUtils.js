 async function getPoolStatus() {
        try {
          const { getServiceUrl } = await import("/js-lib/urlConfig.js");
          const urlKey = "getPoolStatus";
          const serviceUrl = await getServiceUrl(urlKey);
          const response = await fetch(serviceUrl, {
            method: "GET",
            headers: {
              "Content-Type": "application/json",
            },
          });
          if (!response.ok) {
            throw new Error(
              alert("We could not determine the pool status. Please contact the pool administrator at fbpadmin@my-fbp.com"),
              `Failed to fetch pool status with status ${response.status}`,
            );
          } else {
            const data = await response.json();
            console.log("Fetched pool status:", data);
            if ( ! data?.pool_open) {
              alert("FBP Pool is currently closed.  You can view the pick sheet, but you cannot make or change picks at this time.");
              return data.pool_open;
            } else {
              return data.pool_open;
            }
          }
        } catch (error) {
          console.error("Error fetching pool status:", error);
          alert(
            "We could not determine the pool status.  Please contact the pool administrator at fbpadmin@my-fbp.com",
          );
        }
      }
